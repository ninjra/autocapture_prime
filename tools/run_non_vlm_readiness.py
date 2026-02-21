#!/usr/bin/env python3
"""Run Stage1/Stage2 readiness checks that do not require localhost VLM (:8000)."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
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


def _metadata_db_preflight(path: Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"ok": False, "path": str(target), "error": "missing"}
    try:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=1.0)
        cur = conn.cursor()
        count = int(cur.execute("select count(*) from metadata").fetchone()[0])
        conn.close()
        return {"ok": True, "path": str(target), "record_count": count}
    except Exception as exc:
        return {"ok": False, "path": str(target), "error": f"{type(exc).__name__}:{exc}"}


def _run_preflight(
    *,
    db_path: Path,
    sidecar_url: str,
    vlm_url: str,
    timeout_s: float,
) -> dict[str, Any]:
    sidecar = _http_preflight(sidecar_url, timeout_s=timeout_s)
    vlm = _http_preflight(vlm_url, timeout_s=timeout_s)
    metadata = _metadata_db_preflight(db_path)
    ok = bool(sidecar.get("ok", False) and vlm.get("ok", False) and metadata.get("ok", False))
    return {"ok": ok, "sidecar_7411": sidecar, "vlm_8000": vlm, "metadata_db": metadata}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_query_eval_env(*, base_env: dict[str, str], run_dir: Path, dataroot: Path) -> dict[str, str]:
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
    storage_cfg["metadata_path"] = str(dataroot / "metadata.db")
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
    args = parser.parse_args(argv)

    root = _repo_root()
    py = _pick_python(root, str(args.python or ""))

    dataroot = Path(str(args.dataroot)).expanduser()
    db_path = Path(str(args.db or "")).expanduser() if str(args.db or "").strip() else (dataroot / "metadata.db")
    derived_db_path = dataroot / "derived" / "stage1_derived.db"
    run_dir = root / "artifacts" / "non_vlm_readiness" / f"run_{_utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    lineage_json = run_dir / "lineage.json"
    stage1_audit_json = run_dir / "stage1_completeness_audit.json"
    health_json = run_dir / "processing_health.json"
    bench_json = run_dir / "batch_knob_bench.json"
    query_eval_json = run_dir / "query_eval_generic20.json"
    synthetic_gauntlet_json = run_dir / "synthetic_gauntlet_80.json"

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(root)
    base_env["AUTOCAPTURE_DATA_DIR"] = str(dataroot)
    if (dataroot / "config_wsl").exists():
        base_env["AUTOCAPTURE_CONFIG_DIR"] = str(dataroot / "config_wsl")
    elif (dataroot / "config").exists():
        base_env["AUTOCAPTURE_CONFIG_DIR"] = str(dataroot / "config")

    query_eval_env = _build_query_eval_env(base_env=base_env, run_dir=run_dir, dataroot=dataroot)

    steps: list[dict[str, Any]] = []

    if not db_path.exists():
        payload = {
            "ok": False,
            "error": "metadata_db_missing",
            "db": str(db_path),
            "dataroot": str(dataroot),
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
        timeout_s=float(args.preflight_timeout_s),
    )
    if bool(args.require_preflight) and not bool(preflight.get("ok", False)):
        payload = {
            "ok": False,
            "error": "preflight_failed",
            "db": str(db_path),
            "dataroot": str(dataroot),
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
            ("gate_ledger", [py, "tools/gate_ledger.py"]),
            ("gate_security", [py, "tools/gate_security.py"]),
            ("gate_promptops_policy", [py, "tools/gate_promptops_policy.py"]),
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

    required_failures: list[str] = []
    optional_failures: list[str] = []
    optional_skipped: list[str] = []
    for step in steps:
        step_id = str(step.get("id") or "")
        is_optional = step_id in {
            "query_eval_suite_generic20_metadata_only",
            "synthetic_gauntlet_80_metadata_only",
        } and not bool(args.require_query_pass)
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

    payload = {
        "schema_version": 1,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ok": len(required_failures) == 0,
        "dataroot": str(dataroot),
        "db": str(db_path),
        "derived_db": str(derived_db_path),
        "python": str(py),
        "strict_all_frames": bool(args.strict_all_frames),
        "require_query_pass": bool(args.require_query_pass),
        "preflight": preflight,
        "steps": steps,
        "failed_steps": required_failures,
        "optional_failed_steps": optional_failures,
        "optional_skipped_steps": optional_skipped,
        "artifacts": {
            "lineage": str(lineage_json),
            "stage1_completeness_audit": str(stage1_audit_json),
            "processing_health": str(health_json),
            "batch_knob_bench": str(bench_json),
            "query_eval": str(query_eval_json),
            "synthetic_gauntlet": str(synthetic_gauntlet_json),
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
