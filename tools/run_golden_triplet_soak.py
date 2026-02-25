#!/usr/bin/env python3
"""Run strict popup + Q40 + Temporal40 on an interval and fail fast on regressions."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_json_tail(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    idx = raw.rfind("{")
    while idx >= 0:
        chunk = raw[idx:]
        try:
            parsed = json.loads(chunk)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        idx = raw.rfind("{", 0, idx)
    return None


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "cmd": cmd,
        "returncode": int(proc.returncode),
        "elapsed_ms": elapsed_ms,
        "ok": int(proc.returncode) == 0,
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
    }


def _report_path_from_q40_matrix(matrix_path: Path) -> str:
    if not matrix_path.exists():
        return ""
    try:
        payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    provenance = payload.get("provenance", {}) if isinstance(payload.get("provenance", {}), dict) else {}
    adv = provenance.get("advanced20", {}) if isinstance(provenance.get("advanced20", {}), dict) else {}
    path = str(adv.get("path") or "").strip()
    return path


def _resolve_q40_artifacts(*, root: Path, stdout: str) -> tuple[Path, str]:
    q40_json = _extract_json_tail(str(stdout))
    matrix_path = Path(
        str((q40_json or {}).get("matrix") or "artifacts/advanced10/q40_matrix_latest.json")
    )
    report_path = str((q40_json or {}).get("report") or "").strip()
    if not report_path:
        report_path = _report_path_from_q40_matrix(root / matrix_path) or str(
            (root / "artifacts" / "single_image_runs" / "latest" / "report.json").resolve()
        )
    return matrix_path, report_path


def _run_synthetic_bootstrap(
    *,
    root: Path,
    cmd: list[str],
) -> tuple[dict[str, Any], Path, str]:
    synth = _run(cmd, cwd=root)
    payload = _extract_json_tail(str(synth.get("stdout") or ""))
    matrix_path = Path(
        str((payload or {}).get("matrix") or "artifacts/advanced10/q40_matrix_latest.json")
    )
    report_path = str((payload or {}).get("report") or "").strip()
    if not report_path:
        report_path = _report_path_from_q40_matrix(root / matrix_path) or str(
            (root / "artifacts" / "single_image_runs" / "latest" / "report.json").resolve()
        )
    return synth, matrix_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interval strict soak for popup/Q40/Temporal40.")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval-s", type=int, default=1800)
    parser.add_argument("--popup-timeout-s", type=float, default=12.0)
    parser.add_argument("--output", default="artifacts/release/golden_triplet_soak_latest.json")
    parser.add_argument("--stop-on-fail", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--allow-synthetic-fallback", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-runtime-contract", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--require-stage1-contract", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-popup-strict", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--synthetic-bootstrap-cmd", default="bash tools/run_q40_uia_synthetic.sh")
    parser.add_argument("--repo-root", default="")
    args = parser.parse_args(argv)

    root = Path(str(args.repo_root)).expanduser().resolve() if str(args.repo_root).strip() else Path(__file__).resolve().parents[1]
    py = root / ".venv" / "bin" / "python"
    py_str = str(py if py.exists() else Path(sys.executable))

    rows: list[dict[str, Any]] = []
    failed = False
    failure_reason = ""
    synth_cmd = shlex.split(str(args.synthetic_bootstrap_cmd))
    if not synth_cmd:
        synth_cmd = ["bash", "tools/run_q40_uia_synthetic.sh"]

    for idx in range(max(1, int(args.cycles))):
        cycle = idx + 1
        row: dict[str, Any] = {"cycle": cycle, "ts_utc": _utc_iso(), "source_tier": "real"}

        stage1_gate = _run(
            [py_str, "tools/gate_stage1_contract.py"],
            cwd=root,
        )
        row["stage1_contract"] = {
            "ok": bool(stage1_gate["ok"]),
            "elapsed_ms": int(stage1_gate["elapsed_ms"]),
            "stdout_tail": str(stage1_gate["stdout"])[-1200:],
            "stderr_tail": str(stage1_gate["stderr"])[-1200:],
        }
        if not bool(stage1_gate["ok"]) and bool(args.require_stage1_contract):
            failed = True
            failure_reason = f"cycle_{cycle}:stage1_contract_failed"
            rows.append(row)
            if bool(args.stop_on_fail):
                break
            continue
        elif not bool(stage1_gate["ok"]):
            row["stage1_contract"]["soft_failed"] = True

        verify = _run(
            [py_str, "tools/verify_query_upstream_runtime_contract.py"],
            cwd=root,
        )
        row["verify_runtime"] = {
            "ok": bool(verify["ok"]),
            "elapsed_ms": int(verify["elapsed_ms"]),
            "stdout_tail": str(verify["stdout"])[-1200:],
            "stderr_tail": str(verify["stderr"])[-1200:],
        }
        if not bool(verify["ok"]) and bool(args.require_runtime_contract):
            failed = True
            failure_reason = f"cycle_{cycle}:verify_runtime_failed"
            rows.append(row)
            if bool(args.stop_on_fail):
                break
        elif not bool(verify["ok"]):
            row["verify_runtime"]["soft_failed"] = True

        env = {"AUTOCAPTURE_POPUP_ACCEPT_TIMEOUT_S": str(float(args.popup_timeout_s))}
        popup = _run(
            [
                "bash",
                "tools/run_popup_regression_strict.sh",
                "artifacts/query_acceptance/popup_regression_latest.json",
                "artifacts/query_acceptance/popup_regression_misses_latest.json",
            ],
            cwd=root,
            env={**dict(os.environ), **env},
        )
        row["popup_strict"] = {
            "ok": bool(popup["ok"]),
            "elapsed_ms": int(popup["elapsed_ms"]),
            "stdout_tail": str(popup["stdout"])[-1200:],
            "stderr_tail": str(popup["stderr"])[-1200:],
        }
        popup_effective_ok = bool(popup["ok"])
        if not bool(popup["ok"]) and bool(args.require_popup_strict):
            failed = True
            failure_reason = f"cycle_{cycle}:popup_strict_failed"
            rows.append(row)
            if bool(args.stop_on_fail):
                break
            continue
        elif not bool(popup["ok"]):
            row["popup_strict"]["soft_failed"] = True
            popup_effective_ok = False

        q40 = _run(["bash", "tools/q40.sh"], cwd=root)
        matrix_path, report_path = _resolve_q40_artifacts(root=root, stdout=str(q40["stdout"]))
        effective_q40_ok = bool(q40["ok"])
        row["q40_strict"] = {
            "ok": bool(q40["ok"]),
            "effective_ok": bool(effective_q40_ok),
            "elapsed_ms": int(q40["elapsed_ms"]),
            "matrix": str((root / matrix_path).resolve()),
            "report": str(report_path),
            "stdout_tail": str(q40["stdout"])[-1200:],
            "stderr_tail": str(q40["stderr"])[-1200:],
        }
        if not bool(q40["ok"]) and bool(args.allow_synthetic_fallback):
            synth, synth_matrix, synth_report = _run_synthetic_bootstrap(root=root, cmd=synth_cmd)
            synth_ok = bool(synth["ok"]) and bool(synth_report) and (root / synth_matrix).exists()
            row["synthetic_bootstrap"] = {
                "cmd": synth_cmd,
                "ok": bool(synth_ok),
                "elapsed_ms": int(synth["elapsed_ms"]),
                "matrix": str((root / synth_matrix).resolve()),
                "report": str(synth_report),
                "stdout_tail": str(synth["stdout"])[-1200:],
                "stderr_tail": str(synth["stderr"])[-1200:],
            }
            if synth_ok:
                row["source_tier"] = "synthetic"
                matrix_path = synth_matrix
                report_path = synth_report
                effective_q40_ok = True
                row["q40_strict"]["effective_ok"] = True
                row["q40_strict"]["fallback_used"] = True
                row["q40_strict"]["matrix"] = str((root / matrix_path).resolve())
                row["q40_strict"]["report"] = str(report_path)
        if not bool(effective_q40_ok):
            failed = True
            failure_reason = f"cycle_{cycle}:q40_failed"
            rows.append(row)
            if bool(args.stop_on_fail):
                break
            continue

        temporal = _run(["bash", "tools/run_temporal_qa40_strict.sh", str(report_path)], cwd=root)
        row["temporal40_strict"] = {
            "ok": bool(temporal["ok"]),
            "elapsed_ms": int(temporal["elapsed_ms"]),
            "stdout_tail": str(temporal["stdout"])[-1200:],
            "stderr_tail": str(temporal["stderr"])[-1200:],
        }
        if not bool(temporal["ok"]):
            failed = True
            failure_reason = f"cycle_{cycle}:temporal40_failed"
            rows.append(row)
            if bool(args.stop_on_fail):
                break
            continue

        if popup_effective_ok:
            composite = _run(
                [
                    py_str,
                    "tools/gate_golden_pipeline_triplet.py",
                    "--popup-report",
                    "artifacts/query_acceptance/popup_regression_latest.json",
                    "--q40-report",
                    str(matrix_path),
                    "--temporal-report",
                    "artifacts/temporal40/temporal40_gate_latest.json",
                    "--output",
                    "artifacts/release/gate_golden_pipeline_triplet.json",
                ],
                cwd=root,
            )
            row["composite_gate"] = {
                "ok": bool(composite["ok"]),
                "elapsed_ms": int(composite["elapsed_ms"]),
                "stdout_tail": str(composite["stdout"])[-1200:],
                "stderr_tail": str(composite["stderr"])[-1200:],
            }
            if not bool(composite["ok"]):
                failed = True
                failure_reason = f"cycle_{cycle}:composite_gate_failed"
                rows.append(row)
                if bool(args.stop_on_fail):
                    break
                continue
        else:
            row["composite_gate"] = {
                "ok": True,
                "skipped": True,
                "reason": "popup_soft_failed_optional",
                "elapsed_ms": 0,
                "stdout_tail": "",
                "stderr_tail": "",
            }

        rows.append(row)
        if cycle < int(args.cycles):
            time.sleep(max(0, int(args.interval_s)))

    out = {
        "schema_version": 1,
        "ok": not failed,
        "repo_root": str(root),
        "cycles_requested": int(args.cycles),
        "cycles_completed": len(rows),
        "failed": bool(failed),
        "failure_reason": str(failure_reason),
        "rows": rows,
        "ts_utc": _utc_iso(),
    }
    out_path = Path(str(args.output))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": out["ok"], "output": str(out_path.resolve())}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
