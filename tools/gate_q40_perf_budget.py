#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def _extract_last_json(output: str) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for raw in str(output or "").splitlines():
        line = str(raw or "").strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            last = obj
    return last


def evaluate_perf_budget(
    *,
    runtime_s: float,
    matrix: dict[str, Any],
    report: dict[str, Any],
    max_runtime_s: float,
    max_idle_steps: int,
    max_budget_ms: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if float(runtime_s) > float(max_runtime_s):
        reasons.append("runtime_exceeds_budget")
    if not bool(matrix.get("ok", False)):
        reasons.append("matrix_not_ok")
    if int(matrix.get("matrix_evaluated", 0) or 0) != 40:
        reasons.append("matrix_evaluated_not_40")
    if int(matrix.get("matrix_failed", 0) or 0) != 0:
        reasons.append("matrix_failed_nonzero")
    if int(matrix.get("matrix_skipped", 0) or 0) != 0:
        reasons.append("matrix_skipped_nonzero")
    idle = report.get("idle", {}) if isinstance(report.get("idle"), dict) else {}
    steps_taken = int(idle.get("steps_taken", 0) or 0)
    if steps_taken > int(max_idle_steps):
        reasons.append("idle_steps_exceed_budget")
    budget_ms = int(idle.get("budget_ms", 0) or 0)
    if budget_ms > int(max_budget_ms):
        reasons.append("idle_budget_ms_exceed_limit")
    uia_docs = report.get("uia_docs", {}) if isinstance(report.get("uia_docs"), dict) else {}
    if int(uia_docs.get("total", 0) or 0) <= 0:
        reasons.append("uia_docs_missing")
    return len(reasons) == 0, reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate Q40 synthetic run by runtime/perf budgets and strict matrix semantics.")
    parser.add_argument("--runner", default="tools/run_q40_uia_synthetic.sh")
    parser.add_argument("--image", default="")
    parser.add_argument("--report-json", default="", help="Artifact mode: existing report.json path.")
    parser.add_argument("--matrix-json", default="", help="Artifact mode: existing q40 matrix json path.")
    parser.add_argument("--runtime-s", type=float, default=0.0, help="Artifact mode: measured runtime seconds.")
    parser.add_argument("--max-runtime-s", type=float, default=1800.0)
    parser.add_argument("--max-idle-steps", type=int, default=24)
    parser.add_argument("--max-budget-ms", type=int, default=240000)
    parser.add_argument("--out", default="artifacts/advanced10/q40_perf_budget_gate_latest.json")
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {}
    mode = "runner"
    if str(args.report_json or "").strip() and str(args.matrix_json or "").strip():
        mode = "artifact"
        proc_returncode = 0
        runtime_s = float(args.runtime_s)
        report_path = Path(str(args.report_json))
        matrix_path = Path(str(args.matrix_json))
    else:
        runner = Path(str(args.runner))
        if not runner.exists():
            print(json.dumps({"ok": False, "error": "runner_not_found", "runner": str(runner)}))
            return 2
        cmd = ["bash", str(runner)]
        if str(args.image or "").strip():
            cmd.append(str(args.image))
        t0 = time.monotonic()
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        runtime_s = time.monotonic() - t0
        payload = _extract_last_json(f"{proc.stdout}\n{proc.stderr}")
        proc_returncode = int(proc.returncode)
        matrix_path = Path(str(payload.get("matrix") or ""))
        report_path = Path(str(payload.get("report") or ""))

    if not matrix_path.exists():
        print(json.dumps({"ok": False, "error": "matrix_missing", "payload": payload, "mode": mode}))
        return 1
    if not report_path.exists():
        print(json.dumps({"ok": False, "error": "report_missing", "payload": payload, "mode": mode}))
        return 1

    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ok, reasons = evaluate_perf_budget(
        runtime_s=runtime_s,
        matrix=matrix,
        report=report,
        max_runtime_s=float(args.max_runtime_s),
        max_idle_steps=int(args.max_idle_steps),
        max_budget_ms=int(args.max_budget_ms),
    )

    out_payload = {
        "ok": bool(proc_returncode == 0 and ok),
        "mode": mode,
        "runner_returncode": int(proc_returncode),
        "runtime_s": round(float(runtime_s), 3),
        "max_runtime_s": float(args.max_runtime_s),
        "max_idle_steps": int(args.max_idle_steps),
        "max_budget_ms": int(args.max_budget_ms),
        "failure_reasons": reasons,
        "runner_payload": payload,
        "matrix": str(matrix_path),
        "report": str(report_path),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(out_payload["ok"]), "out": str(out_path), "failure_reasons": reasons}, sort_keys=True))
    return 0 if bool(out_payload["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
