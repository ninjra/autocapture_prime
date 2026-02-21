#!/usr/bin/env python3
"""Run Stage1/Stage2 readiness checks that do not require localhost VLM (:8000)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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
    parser.add_argument("--require-query-pass", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--revalidate-markers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--strict-all-frames", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-s", type=int, default=1200)
    args = parser.parse_args(argv)

    root = _repo_root()
    py = _pick_python(root, str(args.python or ""))

    dataroot = Path(str(args.dataroot)).expanduser()
    db_path = Path(str(args.db or "")).expanduser() if str(args.db or "").strip() else (dataroot / "metadata.db")
    derived_db_path = dataroot / "derived" / "stage1_derived.db"
    run_dir = root / "artifacts" / "non_vlm_readiness" / f"run_{_utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    lineage_json = run_dir / "lineage.json"
    health_json = run_dir / "processing_health.json"
    bench_json = run_dir / "batch_knob_bench.json"
    query_eval_json = run_dir / "query_eval_generic20.json"

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(root)
    base_env["AUTOCAPTURE_DATA_DIR"] = str(dataroot)
    if (dataroot / "config_wsl").exists():
        base_env["AUTOCAPTURE_CONFIG_DIR"] = str(dataroot / "config_wsl")
    elif (dataroot / "config").exists():
        base_env["AUTOCAPTURE_CONFIG_DIR"] = str(dataroot / "config")

    query_eval_env = dict(base_env)
    query_eval_env["AUTOCAPTURE_QUERY_METADATA_ONLY"] = "1"
    query_eval_env["AUTOCAPTURE_PROMPTOPS_REVIEW_ON_QUERY"] = "0"
    query_eval_env["AUTOCAPTURE_SKIP_VLM_UNSTABLE"] = "1"

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
                    "tests/test_query_arbitration.py",
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
        eval_step = _run_step(
            step_id="query_eval_suite_generic20_metadata_only",
            cmd=[py, "tools/query_eval_suite.py", "--cases", str(args.cases), "--safe-mode"],
            cwd=root,
            env=query_eval_env,
            timeout_s=int(args.timeout_s),
        )
        try:
            summary = eval_step.get("stdout_json")
            if isinstance(summary, dict):
                query_eval_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
                eval_step["output"] = str(query_eval_json)
        except Exception:
            pass
        steps.append(eval_step)

    required_failures: list[str] = []
    optional_failures: list[str] = []
    optional_skipped: list[str] = []
    for step in steps:
        step_id = str(step.get("id") or "")
        is_optional = step_id == "query_eval_suite_generic20_metadata_only" and not bool(args.require_query_pass)
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
        "steps": steps,
        "failed_steps": required_failures,
        "optional_failed_steps": optional_failures,
        "optional_skipped_steps": optional_skipped,
        "artifacts": {
            "lineage": str(lineage_json),
            "processing_health": str(health_json),
            "batch_knob_bench": str(bench_json),
            "query_eval": str(query_eval_json),
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
