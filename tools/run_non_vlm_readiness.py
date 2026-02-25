#!/usr/bin/env python3
"""Run Stage1/Stage2 readiness checks that do not require localhost VLM (:8000)."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_TRANSIENT_DB_ERROR_MARKERS = (
    "OperationalError:disk I/O error",
    "OperationalError:database is locked",
    "OperationalError:database disk image is malformed",
    "DatabaseError:database disk image is malformed",
    "sqlite3.OperationalError: disk I/O error",
    "sqlite3.DatabaseError: database disk image is malformed",
    "SQLITE_BUSY",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _tail(text: str, *, max_chars: int = 6000) -> str:
    raw = str(text or "")
    if len(raw) <= max_chars:
        return raw
    return raw[-max_chars:]


def _extract_json_tail(text: str) -> dict[str, Any] | None:
    payload = str(text or "").strip()
    if not payload:
        return None
    for line in reversed(payload.splitlines()):
        line = str(line or "").strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _run_step(
    *,
    step_id: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=max(1, int(timeout_s)),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    stdout = str(proc.stdout or "")
    stderr = str(proc.stderr or "")
    return {
        "id": str(step_id),
        "cmd": list(cmd),
        "returncode": int(proc.returncode),
        "ok": int(proc.returncode) == 0,
        "elapsed_ms": int(elapsed_ms),
        "stdout_json": _extract_json_tail(stdout),
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _has_module(py: str, module_name: str) -> bool:
    try:
        proc = subprocess.run(
            [str(py), "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        return int(proc.returncode) == 0
    except Exception:
        return False


def _pick_python(root: Path, requested: str = "") -> str:
    explicit = str(requested or "").strip()
    if explicit:
        return explicit

    current = str(sys.executable or "").strip()
    if current and _has_module(current, "pytest"):
        return current

    local_venv = root / ".venv" / "bin" / "python"
    if local_venv.exists() and _has_module(str(local_venv), "pytest"):
        return str(local_venv)

    return current or "python3"


def _is_transient_db_error(step: dict[str, Any]) -> bool:
    text = "\n".join(
        [
            str(step.get("stdout_tail") or ""),
            str(step.get("stderr_tail") or ""),
            json.dumps(step.get("stdout_json"), sort_keys=True),
        ]
    )
    return any(marker in text for marker in _TRANSIENT_DB_ERROR_MARKERS)


def _is_dpapi_windows_failure(step: dict[str, Any]) -> bool:
    text = "\n".join(
        [
            str(step.get("stdout_tail") or ""),
            str(step.get("stderr_tail") or ""),
            json.dumps(step.get("stdout_json"), sort_keys=True),
        ]
    )
    return "DPAPI unprotect requires Windows" in text


def _step_failed(steps: list[dict[str, Any]], step_id: str) -> bool:
    for step in steps:
        if str(step.get("id") or "") != str(step_id):
            continue
        return not bool(step.get("ok", False))
    return False


def _slug_token(value: str) -> str:
    raw = str(value or "").strip().casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return normalized or "unknown_failure"


def _failure_class_for_step(step: dict[str, Any]) -> str:
    step_id = str(step.get("id") or "").strip()
    stdout_json = step.get("stdout_json")
    error_text = ""
    if isinstance(stdout_json, dict):
        error_text = str(
            stdout_json.get("error")
            or stdout_json.get("blocked_reason")
            or stdout_json.get("reason")
            or ""
        ).strip()
    if not error_text:
        stderr_text = str(step.get("stderr_tail") or "").strip()
        if stderr_text:
            error_text = str(stderr_text.splitlines()[-1]).strip()
    if not error_text:
        stdout_text = str(step.get("stdout_tail") or "").strip()
        if stdout_text:
            error_text = str(stdout_text.splitlines()[-1]).strip()

    low = error_text.casefold()
    if "instance_lock_held" in low:
        return "instance_lock_held"
    if "missing capability: storage.metadata" in low or "missing_capability:storage.metadata" in low:
        return "missing_capability_storage_metadata"
    if "dpapi unprotect requires windows" in low:
        return "dpapi_windows_required"
    if any(
        marker in low
        for marker in (
            "operationalerror:disk i/o error",
            "operationalerror:database is locked",
            "database disk image is malformed",
            "sqlite_busy",
        )
    ):
        return "metadata_db_transient_io"
    if "timeout" in low:
        return "timeout"
    if error_text:
        return _slug_token(error_text)
    return f"step_{_slug_token(step_id)}"


def _failure_class_counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for step in steps:
        if bool(step.get("ok", False)):
            continue
        if bool(step.get("skipped", False)):
            continue
        counts[_failure_class_for_step(step)] += 1
    return {key: int(counts[key]) for key in sorted(counts)}


def _run_step_with_retry(
    *,
    step_id: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
    retries: int = 2,
    retry_delay_s: int = 2,
) -> dict[str, Any]:
    total_attempts = max(1, int(retries) + 1)
    last: dict[str, Any] | None = None
    for attempt in range(1, total_attempts + 1):
        step = _run_step(step_id=step_id, cmd=cmd, cwd=cwd, env=env, timeout_s=timeout_s)
        step["attempt"] = int(attempt)
        step["attempts_total"] = int(total_attempts)
        step["retried"] = bool(attempt > 1)
        if bool(step.get("ok", False)) or not _is_transient_db_error(step):
            return step
        last = step
        if attempt < total_attempts:
            time.sleep(max(1, int(retry_delay_s)))
    return last or _run_step(step_id=step_id, cmd=cmd, cwd=cwd, env=env, timeout_s=timeout_s)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _http_preflight(url: str, *, timeout_s: float) -> dict[str, Any]:
    target = str(url or "").strip()
    if not target:
        return {"ok": False, "url": target, "status": 0, "error": "missing_url"}
    try:
        req = urllib.request.Request(target, method="GET")
        with urllib.request.urlopen(req, timeout=max(0.2, float(timeout_s))) as resp:  # noqa: S310 - localhost only
            code = int(getattr(resp, "status", 200) or 200)
            body_raw = resp.read(512)
            body = body_raw.decode("utf-8", errors="replace").strip()
        return {"ok": 200 <= code < 300, "url": target, "status": code, "body": body}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": target, "status": int(exc.code), "error": f"http_error:{exc.reason}"}
    except Exception as exc:
        return {"ok": False, "url": target, "status": 0, "error": f"{type(exc).__name__}:{exc}"}


def _http_json_request(
    *,
    url: str,
    timeout_s: float,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = str(url or "").strip()
    if not target:
        return {"ok": False, "url": target, "status": 0, "error": "missing_url", "json": {}}
    raw_data: bytes | None = None
    req_headers = dict(headers or {})
    if payload is not None:
        req_headers.setdefault("Content-Type", "application/json")
        raw_data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(target, method=str(method or "GET").upper(), headers=req_headers, data=raw_data)
        with urllib.request.urlopen(req, timeout=max(0.2, float(timeout_s))) as resp:  # noqa: S310 - localhost only
            code = int(getattr(resp, "status", 200) or 200)
            body_raw = resp.read(4096)
            body = body_raw.decode("utf-8", errors="replace").strip()
        parsed: dict[str, Any] = {}
        if body:
            try:
                obj = json.loads(body)
                if isinstance(obj, dict):
                    parsed = obj
            except Exception:
                parsed = {}
        return {
            "ok": 200 <= code < 300,
            "url": target,
            "status": code,
            "body": body,
            "json": parsed,
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "url": target,
            "status": int(exc.code),
            "error": f"http_error:{exc.reason}",
            "json": {},
        }
    except Exception as exc:
        return {"ok": False, "url": target, "status": 0, "error": f"{type(exc).__name__}:{exc}", "json": {}}


def _popup_query_preflight(
    *,
    sidecar_base_url: str,
    popup_path: str,
    auth_token_path: str,
    query_text: str,
    max_citations: int,
    timeout_s: float,
) -> dict[str, Any]:
    base = str(sidecar_base_url or "").strip().rstrip("/")
    popup_url = str(popup_path or "").strip()
    token_url = str(auth_token_path or "").strip()
    if base:
        if not popup_url.startswith("http://") and not popup_url.startswith("https://"):
            popup_url = urljoin(base + "/", popup_url.lstrip("/"))
        if not token_url.startswith("http://") and not token_url.startswith("https://"):
            token_url = urljoin(base + "/", token_url.lstrip("/"))
    token_resp = _http_json_request(url=token_url, timeout_s=timeout_s, method="GET")
    token = str((token_resp.get("json") if isinstance(token_resp.get("json"), dict) else {}).get("token") or "").strip()
    if not bool(token_resp.get("ok", False)) or not token:
        return {
            "ok": False,
            "error": "popup_token_unavailable",
            "sidecar_base_url": base,
            "token_url": token_url,
            "popup_url": popup_url,
            "token_probe": token_resp,
            "popup_response": {},
            "forbidden_reasons": [],
        }
    popup_resp = _http_json_request(
        url=popup_url,
        timeout_s=timeout_s,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        payload={"query": str(query_text or "status check"), "max_citations": int(max(1, max_citations))},
    )
    popup_json = popup_resp.get("json") if isinstance(popup_resp.get("json"), dict) else {}
    blocked_reason = str(popup_json.get("processing_blocked_reason") or "")
    state = str(popup_json.get("state") or "")
    error_text = str(popup_json.get("error") or "")
    forbidden = []
    for token_val in ("query_compute_disabled", "autocapture_upstream_unreachable"):
        if blocked_reason == token_val:
            forbidden.append(token_val)
        if token_val in error_text:
            forbidden.append(token_val)
    forbidden = sorted(set(forbidden))
    ok = bool(popup_resp.get("ok", False)) and len(forbidden) == 0
    return {
        "ok": bool(ok),
        "error": "" if ok else ("popup_forbidden_block_reason" if forbidden else "popup_query_failed"),
        "sidecar_base_url": base,
        "token_url": token_url,
        "popup_url": popup_url,
        "query": str(query_text or ""),
        "popup_state": state,
        "popup_blocked_reason": blocked_reason,
        "forbidden_reasons": forbidden,
        "token_probe": token_resp,
        "popup_response": popup_resp,
    }


def _metadata_db_preflight(path: Path, *, attempts: int = 4) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"ok": False, "path": str(target), "error": "missing"}
    safe_attempts = max(1, int(attempts))
    delay_s = 0.2
    last_exc: BaseException | None = None
    for attempt in range(1, safe_attempts + 1):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=1.0)
            cur = conn.cursor()
            count = int(cur.execute("select count(*) from metadata").fetchone()[0])
            return {
                "ok": True,
                "path": str(target),
                "record_count": count,
                "attempts": int(attempt),
                "retried": bool(attempt > 1),
            }
        except Exception as exc:
            last_exc = exc
            if attempt >= safe_attempts or not _is_transient_db_error(
                {
                    "stdout_tail": "",
                    "stderr_tail": f"{type(exc).__name__}:{exc}",
                    "stdout_json": {},
                }
            ):
                break
            time.sleep(delay_s)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    assert last_exc is not None
    return {"ok": False, "path": str(target), "error": f"{type(last_exc).__name__}:{last_exc}", "attempts": int(safe_attempts)}


def _resolve_metadata_db_path(*, dataroot: Path, explicit_db: str) -> tuple[Path, dict[str, Any]]:
    explicit = str(explicit_db or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path, {"selected": str(path), "strategy": "explicit"}

    primary = dataroot / "metadata.db"
    live = dataroot / "metadata.live.db"

    if not primary.exists() and live.exists():
        return live, {"selected": str(live), "strategy": "live_only"}
    if not live.exists():
        return primary, {"selected": str(primary), "strategy": "primary_only"}

    primary_probe = _metadata_db_preflight(primary, attempts=1)
    if bool(primary_probe.get("ok", False)):
        return primary, {"selected": str(primary), "strategy": "primary_readable", "primary_probe": primary_probe}

    live_probe = _metadata_db_preflight(live, attempts=1)
    if bool(live_probe.get("ok", False)):
        return (
            live,
            {
                "selected": str(live),
                "strategy": "fallback_live_readable",
                "primary_probe": primary_probe,
                "live_probe": live_probe,
            },
        )

    return (
        primary,
        {
            "selected": str(primary),
            "strategy": "primary_unreadable_live_unreadable",
            "primary_probe": primary_probe,
            "live_probe": live_probe,
        },
    )


def _run_preflight(
    *,
    db_path: Path,
    sidecar_url: str,
    vlm_url: str,
    popup_base_url: str,
    popup_path: str,
    auth_token_path: str,
    popup_query: str,
    popup_max_citations: int,
    timeout_s: float,
) -> dict[str, Any]:
    sidecar = _http_preflight(sidecar_url, timeout_s=timeout_s)
    vlm = _http_preflight(vlm_url, timeout_s=timeout_s)
    metadata = _metadata_db_preflight(db_path)
    popup = _popup_query_preflight(
        sidecar_base_url=popup_base_url,
        popup_path=popup_path,
        auth_token_path=auth_token_path,
        query_text=popup_query,
        max_citations=popup_max_citations,
        timeout_s=timeout_s,
    )
    ok = bool(sidecar.get("ok", False) and vlm.get("ok", False) and metadata.get("ok", False) and popup.get("ok", False))
    return {"ok": ok, "sidecar_7411": sidecar, "vlm_8000": vlm, "metadata_db": metadata, "popup_query": popup}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_query_eval_env(*, base_env: dict[str, str], run_dir: Path, dataroot: Path, metadata_db_path: Path) -> dict[str, str]:
    env = dict(base_env)
    query_data_dir = run_dir / "query_eval_data"
    query_data_dir.mkdir(parents=True, exist_ok=True)
    query_cfg_dir = run_dir / "query_eval_config"
    query_cfg_dir.mkdir(parents=True, exist_ok=True)

    base_cfg_dir = Path(str(base_env.get("AUTOCAPTURE_CONFIG_DIR") or "")).expanduser()
    base_user = _load_json_object(base_cfg_dir / "user.json") if str(base_cfg_dir).strip() else {}
    user_cfg = dict(base_user)
    storage_cfg = user_cfg.get("storage")
    if not isinstance(storage_cfg, dict):
        storage_cfg = {}
    storage_cfg["data_dir"] = str(query_data_dir)
    # Honor the caller-selected DB (for example metadata.live.db) instead of
    # hard-wiring metadata.db, so readiness query eval reflects the same corpus
    # used by lineage and completeness checks.
    storage_cfg["metadata_path"] = str(metadata_db_path)
    if not str(storage_cfg.get("lexical_path") or "").strip():
        storage_cfg["lexical_path"] = str(dataroot / "lexical.db")
    if not str(storage_cfg.get("vector_path") or "").strip():
        storage_cfg["vector_path"] = str(dataroot / "vector.db")
    if not str(storage_cfg.get("media_dir") or "").strip():
        storage_cfg["media_dir"] = str(dataroot / "media")
    user_cfg["storage"] = storage_cfg
    plugins_cfg = user_cfg.get("plugins")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    locks_cfg = plugins_cfg.get("locks")
    if not isinstance(locks_cfg, dict):
        locks_cfg = {}
    # Readiness-only query harness: avoid lockfile drift from blocking metadata checks.
    locks_cfg["enforce"] = False
    plugins_cfg["locks"] = locks_cfg
    user_cfg["plugins"] = plugins_cfg
    (query_cfg_dir / "user.json").write_text(json.dumps(user_cfg, indent=2, sort_keys=True), encoding="utf-8")

    env["AUTOCAPTURE_CONFIG_DIR"] = str(query_cfg_dir)
    env["AUTOCAPTURE_DATA_DIR"] = str(query_data_dir)
    env["AUTOCAPTURE_QUERY_METADATA_ONLY"] = "1"
    env["AUTOCAPTURE_PROMPTOPS_REVIEW_ON_QUERY"] = "0"
    env["AUTOCAPTURE_SKIP_VLM_UNSTABLE"] = "1"
    return env


def _is_retryable_query_step_error(step: dict[str, Any]) -> bool:
    text = "\n".join(
        [
            str(step.get("stdout_tail") or ""),
            str(step.get("stderr_tail") or ""),
            json.dumps(step.get("stdout_json"), sort_keys=True),
        ]
    )
    markers = ("instance_lock_held", "missing_capability:storage.metadata")
    return any(marker in text for marker in markers) or _is_transient_db_error(step)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run non-VLM readiness checks for Stage1 + metadata-only query path.")
    parser.add_argument("--dataroot", default="/mnt/d/autocapture")
    parser.add_argument("--db", default="", help="Optional explicit metadata DB path (defaults to <dataroot>/metadata.db).")
    parser.add_argument("--python", default="", help="Optional Python interpreter for child steps (default: auto-detect).")
    parser.add_argument("--cases", default="docs/query_eval_cases_generic20.json", help="Generic query-eval case file.")
    parser.add_argument("--output", default="artifacts/non_vlm_readiness/non_vlm_readiness_latest.json")
    parser.add_argument("--run-pytest", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-gates", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-query-eval", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-synthetic-gauntlet", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-query-pass", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--revalidate-markers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--strict-all-frames", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-s", type=int, default=1200)
    parser.add_argument("--require-preflight", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--preflight-timeout-s", type=float, default=2.5)
    parser.add_argument("--preflight-sidecar-url", default="http://127.0.0.1:7411/health")
    parser.add_argument("--preflight-vlm-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--preflight-popup-base-url", default="http://127.0.0.1:7411")
    parser.add_argument("--preflight-popup-path", default="/api/query/popup")
    parser.add_argument("--preflight-popup-token-path", default="/api/auth/token")
    parser.add_argument("--preflight-popup-query", default="status check")
    parser.add_argument("--preflight-popup-max-citations", type=int, default=6)
    parser.add_argument("--run-real-corpus-strict", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-real-corpus-strict", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args(argv)

    root = _repo_root()
    py = _pick_python(root, str(args.python or ""))

    dataroot = Path(str(args.dataroot)).expanduser()
    db_path, metadata_db_resolution = _resolve_metadata_db_path(
        dataroot=dataroot,
        explicit_db=str(args.db or ""),
    )
    derived_db_path = dataroot / "derived" / "stage1_derived.db"
    run_dir = root / "artifacts" / "non_vlm_readiness" / f"run_{_utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    lineage_json = run_dir / "lineage.json"
    stage1_audit_json = run_dir / "stage1_completeness_audit.json"
    health_json = run_dir / "processing_health.json"
    bench_json = run_dir / "batch_knob_bench.json"
    plugin_enablement_json = run_dir / "gate_plugin_enablement.json"
    stage1_contract_json = run_dir / "gate_stage1_contract.json"
    audit_integrity_json = run_dir / "gate_audit_log_integrity.json"
    release_quickcheck_json = run_dir / "release_quickcheck.json"
    query_eval_json = run_dir / "query_eval_generic20.json"
    synthetic_gauntlet_json = run_dir / "synthetic_gauntlet_80.json"
    real_corpus_strict_json = run_dir / "real_corpus_strict_matrix.json"

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(root)
    base_env["AUTOCAPTURE_DATA_DIR"] = str(dataroot)
    if (dataroot / "config_wsl").exists():
        base_env["AUTOCAPTURE_CONFIG_DIR"] = str(dataroot / "config_wsl")
    elif (dataroot / "config").exists():
        base_env["AUTOCAPTURE_CONFIG_DIR"] = str(dataroot / "config")

    query_eval_env = _build_query_eval_env(
        base_env=base_env,
        run_dir=run_dir,
        dataroot=dataroot,
        metadata_db_path=db_path,
    )

    steps: list[dict[str, Any]] = []

    if not db_path.exists():
        payload = {
            "ok": False,
            "error": "metadata_db_missing",
            "db": str(db_path),
            "dataroot": str(dataroot),
            "metadata_db_resolution": metadata_db_resolution,
        }
        out_path = root / str(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 2

    preflight = _run_preflight(
        db_path=db_path,
        sidecar_url=str(args.preflight_sidecar_url),
        vlm_url=str(args.preflight_vlm_url),
        popup_base_url=str(args.preflight_popup_base_url),
        popup_path=str(args.preflight_popup_path),
        auth_token_path=str(args.preflight_popup_token_path),
        popup_query=str(args.preflight_popup_query),
        popup_max_citations=int(args.preflight_popup_max_citations),
        timeout_s=float(args.preflight_timeout_s),
    )
    if bool(args.require_preflight) and not bool(preflight.get("ok", False)):
        payload = {
            "ok": False,
            "error": "preflight_failed",
            "db": str(db_path),
            "dataroot": str(dataroot),
            "metadata_db_resolution": metadata_db_resolution,
            "preflight": preflight,
        }
        out_path = root / str(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 3

    if bool(args.revalidate_markers):
        steps.append(
            _run_step_with_retry(
                step_id="backfill_uia_obs_docs",
                cmd=[
                    py,
                    "tools/migrations/backfill_uia_obs_docs.py",
                    "--db",
                    str(db_path),
                    "--derived-db",
                    str(derived_db_path),
                    "--dataroot",
                    str(dataroot),
                    "--wait-stable-seconds",
                    "2",
                    "--wait-timeout-seconds",
                    "120",
                ],
                cwd=root,
                env=base_env,
                timeout_s=int(args.timeout_s),
                retries=3,
                retry_delay_s=2,
            )
        )
        if _step_failed(steps, "backfill_uia_obs_docs"):
            steps.append(
                _run_step(
                    step_id="backfill_uia_obs_docs_dry_run",
                    cmd=[
                        py,
                        "tools/migrations/backfill_uia_obs_docs.py",
                        "--db",
                        str(db_path),
                        "--derived-db",
                        str(derived_db_path),
                        "--dataroot",
                        str(dataroot),
                        "--dry-run",
                    ],
                    cwd=root,
                    env=base_env,
                    timeout_s=int(args.timeout_s),
                )
            )
        steps.append(
            _run_step_with_retry(
                step_id="revalidate_stage1_markers",
                cmd=[
                    py,
                    "tools/migrations/revalidate_stage1_markers.py",
                    "--db",
                    str(db_path),
                    "--derived-db",
                    str(derived_db_path),
                ],
                cwd=root,
                env=base_env,
                timeout_s=int(args.timeout_s),
                retries=3,
                retry_delay_s=2,
            )
        )
        if _step_failed(steps, "revalidate_stage1_markers"):
            steps.append(
                _run_step(
                    step_id="revalidate_stage1_markers_dry_run",
                    cmd=[
                        py,
                        "tools/migrations/revalidate_stage1_markers.py",
                        "--db",
                        str(db_path),
                        "--derived-db",
                        str(derived_db_path),
                        "--dry-run",
                    ],
                    cwd=root,
                    env=base_env,
                    timeout_s=int(args.timeout_s),
                )
            )

    lineage_cmd = [
        py,
        "tools/validate_stage1_lineage.py",
        "--db",
        str(db_path),
        "--derived-db",
        str(derived_db_path),
        "--strict",
        "--output",
        str(lineage_json),
    ]
    if bool(args.strict_all_frames):
        lineage_cmd.append("--strict-all-frames")
    steps.append(
        _run_step_with_retry(
            step_id="validate_stage1_lineage",
            cmd=lineage_cmd,
            cwd=root,
            env=base_env,
            timeout_s=int(args.timeout_s),
            retries=2,
            retry_delay_s=2,
        )
    )
    steps.append(
        _run_step_with_retry(
            step_id="stage1_completeness_audit",
            cmd=[
                py,
                "tools/soak/stage1_completeness_audit.py",
                "--db",
                str(db_path),
                "--derived-db",
                str(derived_db_path),
                "--gap-seconds",
                "120",
                "--samples",
                "20",
                "--output",
                str(stage1_audit_json),
            ],
            cwd=root,
            env=base_env,
            timeout_s=int(args.timeout_s),
            retries=2,
            retry_delay_s=2,
        )
    )

    steps.append(
        _run_step(
            step_id="processing_health_snapshot",
            cmd=[py, "tools/soak/processing_health_snapshot.py", "--manifests", str(dataroot / "facts" / "landscape_manifests.ndjson"), "--tail", "120", "--output", str(health_json)],
            cwd=root,
            env=base_env,
            timeout_s=int(args.timeout_s),
        )
    )
    steps.append(
        _run_step(
            step_id="bench_batch_knobs_synthetic",
            cmd=[py, "tools/bench_batch_knobs_synthetic.py", "--workers", "1,2,4,6", "--output", str(bench_json)],
            cwd=root,
            env=base_env,
            timeout_s=int(args.timeout_s),
        )
    )

    if bool(args.run_pytest):
        steps.append(
            _run_step(
                step_id="pytest_non_vlm_subset",
                cmd=[
                    py,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_validate_stage1_lineage_tool.py",
                    "tests/test_stage1_marker_revalidation_migration.py",
                    "tests/test_processing_health_snapshot_tool.py",
                    "tests/test_stage1_completeness_audit_tool.py",
                    "tests/test_gate_stage1_contract.py",
                    "tests/test_gate_audit_log_integrity.py",
                    "tests/test_query_arbitration.py",
                    "tests/test_query_eval_suite_exact.py",
                    "tests/test_run_synthetic_gauntlet_tool.py",
                    "tests/test_schedule_extract_from_query.py",
                    "tests/test_runtime_batch_adaptive_parallelism.py",
                    "tests/test_stage1_no_vlm_profile.py",
                ],
                cwd=root,
                env=base_env,
                timeout_s=int(args.timeout_s),
            )
        )

    if bool(args.run_gates):
        for gate_id, gate_cmd in (
            ("gate_plugin_enablement", [py, "tools/gate_plugin_enablement.py", "--output", str(plugin_enablement_json)]),
            (
                "gate_stage1_contract",
                [
                    py,
                    "tools/gate_stage1_contract.py",
                    "--audit-report",
                    str(stage1_audit_json),
                    "--output",
                    str(stage1_contract_json),
                ],
            ),
            (
                "gate_audit_log_integrity",
                [
                    py,
                    "tools/gate_audit_log_integrity.py",
                    "--output",
                    str(audit_integrity_json),
                    "--allow-missing",
                ],
            ),
            ("gate_ledger", [py, "tools/gate_ledger.py"]),
            ("gate_security", [py, "tools/gate_security.py"]),
            ("gate_promptops_policy", [py, "tools/gate_promptops_policy.py"]),
            ("release_quickcheck", [py, "tools/release_quickcheck.py", "--output", str(release_quickcheck_json)]),
        ):
            steps.append(
                _run_step(
                    step_id=gate_id,
                    cmd=gate_cmd,
                    cwd=root,
                    env=base_env,
                    timeout_s=int(args.timeout_s),
                )
            )

    if bool(args.run_query_eval):
        eval_step = _run_step_with_retry(
            step_id="query_eval_suite_generic20_metadata_only",
            cmd=[py, "tools/query_eval_suite.py", "--cases", str(args.cases), "--safe-mode"],
            cwd=root,
            env=query_eval_env,
            timeout_s=int(args.timeout_s),
            retries=2,
            retry_delay_s=2,
        )
        if not bool(eval_step.get("ok", False)) and _is_retryable_query_step_error(eval_step):
            eval_step = _run_step_with_retry(
                step_id="query_eval_suite_generic20_metadata_only",
                cmd=[py, "tools/query_eval_suite.py", "--cases", str(args.cases), "--safe-mode"],
                cwd=root,
                env=query_eval_env,
                timeout_s=int(args.timeout_s),
                retries=3,
                retry_delay_s=3,
            )
        try:
            summary = eval_step.get("stdout_json")
            if isinstance(summary, dict):
                query_eval_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
                eval_step["output"] = str(query_eval_json)
        except Exception:
            pass
        steps.append(eval_step)

    if bool(args.run_synthetic_gauntlet):
        gauntlet_step = _run_step_with_retry(
            step_id="synthetic_gauntlet_80_metadata_only",
            cmd=[
                py,
                "tools/run_synthetic_gauntlet.py",
                "--metadata-only",
                "--safe-mode",
                "--output",
                str(synthetic_gauntlet_json),
            ],
            cwd=root,
            env=query_eval_env,
            timeout_s=int(args.timeout_s),
            retries=2,
            retry_delay_s=2,
        )
        if not bool(gauntlet_step.get("ok", False)) and _is_retryable_query_step_error(gauntlet_step):
            gauntlet_step = _run_step_with_retry(
                step_id="synthetic_gauntlet_80_metadata_only",
                cmd=[
                    py,
                    "tools/run_synthetic_gauntlet.py",
                    "--metadata-only",
                    "--safe-mode",
                    "--output",
                    str(synthetic_gauntlet_json),
                ],
                cwd=root,
                env=query_eval_env,
                timeout_s=int(args.timeout_s),
                retries=3,
                retry_delay_s=3,
            )
        try:
            summary = gauntlet_step.get("stdout_json")
            if isinstance(summary, dict):
                metrics = summary.get("summary", {}) if isinstance(summary.get("summary"), dict) else {}
                gauntlet_step["strict_evaluated"] = int(metrics.get("strict_evaluated", 0) or 0)
                gauntlet_step["strict_failed"] = int(metrics.get("strict_failed", 0) or 0)
                gauntlet_step["output"] = str(synthetic_gauntlet_json)
        except Exception:
            pass
        steps.append(gauntlet_step)

    if bool(args.run_real_corpus_strict):
        strict_step = _run_step_with_retry(
            step_id="real_corpus_strict_matrix",
            cmd=[
                py,
                "tools/run_real_corpus_readiness.py",
                "--stage1-audit-json",
                str(stage1_audit_json),
                "--out",
                str(real_corpus_strict_json),
                "--latest-report-md",
                str(run_dir / "real_corpus_strict_latest.md"),
            ],
            cwd=root,
            env=base_env,
            timeout_s=int(args.timeout_s),
            retries=1,
            retry_delay_s=2,
        )
        if isinstance(strict_step.get("stdout_json"), dict):
            strict_step["output"] = str(real_corpus_strict_json)
        steps.append(strict_step)

    required_failures: list[str] = []
    optional_failures: list[str] = []
    optional_skipped: list[str] = []
    for step in steps:
        step_id = str(step.get("id") or "")
        is_optional = step_id in {
            "query_eval_suite_generic20_metadata_only",
            "synthetic_gauntlet_80_metadata_only",
        } and not bool(args.require_query_pass)
        if step_id == "real_corpus_strict_matrix" and not bool(args.require_real_corpus_strict):
            is_optional = True
        if not bool(step.get("ok", False)):
            if is_optional and _is_dpapi_windows_failure(step):
                step["skipped"] = True
                step["skip_reason"] = "dpapi_windows_required_in_wsl"
                optional_skipped.append(step_id)
                continue
            if is_optional:
                optional_failures.append(step_id)
            else:
                required_failures.append(step_id)
            continue
        if step_id == "query_eval_suite_generic20_metadata_only" and bool(args.require_query_pass):
            row = step.get("stdout_json")
            if isinstance(row, dict) and not bool(row.get("ok", False)):
                required_failures.append(step_id)
        if step_id == "synthetic_gauntlet_80_metadata_only" and bool(args.require_query_pass):
            row = step.get("stdout_json")
            if isinstance(row, dict) and not bool(row.get("ok", False)):
                required_failures.append(step_id)

    processing_health_summary: dict[str, Any] = {}
    for step in steps:
        if str(step.get("id") or "") == "processing_health_snapshot":
            row = step.get("stdout_json")
            if isinstance(row, dict):
                processing_health_summary = row
            break
    stage1_summary = _load_json_object(stage1_audit_json).get("summary", {}) if stage1_audit_json.exists() else {}
    strict_payload = _load_json_object(real_corpus_strict_json) if real_corpus_strict_json.exists() else {}
    plugin_enablement_payload = _load_json_object(plugin_enablement_json) if plugin_enablement_json.exists() else {}
    stage1_contract_payload = _load_json_object(stage1_contract_json) if stage1_contract_json.exists() else {}
    audit_integrity_payload = _load_json_object(audit_integrity_json) if audit_integrity_json.exists() else {}
    release_quickcheck_payload = _load_json_object(release_quickcheck_json) if release_quickcheck_json.exists() else {}
    failure_class_counts = _failure_class_counts(steps)
    top_failure_classes = [
        {"failure_class": key, "count": int(val)}
        for key, val in sorted(failure_class_counts.items(), key=lambda item: (-int(item[1]), item[0]))[:5]
    ]

    payload = {
        "schema_version": 1,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ok": len(required_failures) == 0,
        "dataroot": str(dataroot),
        "db": str(db_path),
        "metadata_db_resolution": metadata_db_resolution,
        "derived_db": str(derived_db_path),
        "python": str(py),
        "strict_all_frames": bool(args.strict_all_frames),
        "require_query_pass": bool(args.require_query_pass),
        "preflight": preflight,
        "steps": steps,
        "failed_steps": required_failures,
        "optional_failed_steps": optional_failures,
        "optional_skipped_steps": optional_skipped,
        "failure_class_counts": failure_class_counts,
        "real_corpus_strict": strict_payload,
        "readiness_report": {
            "service_reachability": preflight,
            "top_failure_classes": top_failure_classes,
            "plugin_enablement": {
                "ok": bool(plugin_enablement_payload.get("ok", False)),
                "required_count": int(plugin_enablement_payload.get("required_count", 0) or 0),
                "failed_count": int(plugin_enablement_payload.get("failed_count", 0) or 0),
                "coverage_totals": (
                    (plugin_enablement_payload.get("plugin_coverage", {}) if isinstance(plugin_enablement_payload.get("plugin_coverage"), dict) else {})
                    .get("totals", {})
                ),
            },
            "stage1_contract": {
                "ok": bool(stage1_contract_payload.get("ok", False)),
                "reasons": (
                    ((stage1_contract_payload.get("result", {}) if isinstance(stage1_contract_payload.get("result"), dict) else {}).get("reasons", []))
                    if isinstance(stage1_contract_payload, dict)
                    else []
                ),
                "counts": (
                    ((stage1_contract_payload.get("result", {}) if isinstance(stage1_contract_payload.get("result"), dict) else {}).get("counts", {}))
                    if isinstance(stage1_contract_payload, dict)
                    else {}
                ),
            },
            "audit_integrity": {
                "ok": bool(audit_integrity_payload.get("ok", False)),
                "issues": audit_integrity_payload.get("issues", {}) if isinstance(audit_integrity_payload, dict) else {},
                "counts": audit_integrity_payload.get("counts", {}) if isinstance(audit_integrity_payload, dict) else {},
            },
            "strict_matrix": {
                "ok": bool(strict_payload.get("ok", False)),
                "matrix_total": int(strict_payload.get("matrix_total", 0) or 0),
                "matrix_evaluated": int(strict_payload.get("matrix_evaluated", 0) or 0),
                "matrix_failed": int(strict_payload.get("matrix_failed", 0) or 0),
                "matrix_skipped": int(strict_payload.get("matrix_skipped", 0) or 0),
                "failure_cause_counts": strict_payload.get("strict_failure_cause_counts", {}),
            },
            "release_quickcheck": {
                "ok": bool(release_quickcheck_payload.get("ok", False)),
                "top_failure_reasons": release_quickcheck_payload.get("top_failure_reasons", []),
                "statuses": release_quickcheck_payload.get("statuses", {}),
                "stage_coverage": release_quickcheck_payload.get("stage_coverage", {}),
            },
            "stage1_backlog_risk": {
                "frames_total": int((stage1_summary or {}).get("frames_total", 0) or 0),
                "frames_queryable": int((stage1_summary or {}).get("frames_queryable", 0) or 0),
                "frames_blocked": int((stage1_summary or {}).get("frames_blocked", 0) or 0),
                "processing_latest": (processing_health_summary or {}).get("latest", {}),
                "processing_alerts": (processing_health_summary or {}).get("alerts", []),
            },
        },
        "artifacts": {
            "lineage": str(lineage_json),
            "stage1_completeness_audit": str(stage1_audit_json),
            "processing_health": str(health_json),
            "batch_knob_bench": str(bench_json),
            "plugin_enablement_gate": str(plugin_enablement_json),
            "stage1_contract_gate": str(stage1_contract_json),
            "audit_integrity_gate": str(audit_integrity_json),
            "release_quickcheck": str(release_quickcheck_json),
            "query_eval": str(query_eval_json),
            "synthetic_gauntlet": str(synthetic_gauntlet_json),
            "real_corpus_strict_matrix": str(real_corpus_strict_json),
        },
    }
    out_path = root / str(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
