#!/usr/bin/env python3
"""Fail-closed release gate runner.

Runs the required gate manifest and blocks release if any step returns:
- non-zero process exit
- explicit non-pass status markers (fail/error/warn/skip)
- explicit ok=false marker
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PASS_STATUSES = {"pass", "passed", "ok", "success"}
NON_PASS_STATUSES = {"fail", "failed", "error", "warn", "warning", "skip", "skipped"}


@dataclass(frozen=True)
class GateStep:
    id: str
    cmd: list[str]
    artifact: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_manifest(py: str) -> list[GateStep]:
    steps: list[GateStep] = [
        GateStep("gate_phase0", [py, "tools/gate_phase0.py"], "artifacts/phase0/gate_phase0.json"),
        GateStep("gate_phase1", [py, "tools/gate_phase1.py"], "artifacts/phase1/gate_phase1.json"),
        GateStep("gate_phase2", [py, "tools/gate_phase2.py"], "artifacts/phase2/gate_phase2.json"),
        GateStep("gate_phase3", [py, "tools/gate_phase3.py"], "artifacts/phase3/gate_phase3.json"),
        GateStep("gate_phase4", [py, "tools/gate_phase4.py"], "artifacts/phase4/gate_phase4.json"),
        GateStep("gate_phase5", [py, "tools/gate_phase5.py"], "artifacts/phase5/gate_phase5.json"),
        GateStep("gate_phase6", [py, "tools/gate_phase6.py"], "artifacts/phase6/gate_phase6.json"),
        GateStep("gate_phase7", [py, "tools/gate_phase7.py"], "artifacts/phase7/gate_phase7.json"),
        GateStep("gate_phase8", [py, "tools/gate_phase8.py"], "artifacts/phase8/gate_phase8.json"),
        GateStep("gate_security", [py, "tools/gate_security.py"], "artifacts/security/gate_security.json"),
        GateStep("gate_perf", [py, "tools/gate_perf.py"], "artifacts/perf/gate_perf.json"),
        GateStep("gate_slo_budget", [py, "tools/gate_slo_budget.py"], None),
        GateStep("gate_telemetry_schema", [py, "tools/gate_telemetry_schema.py"], None),
        GateStep(
            "gate_promptops_policy",
            [py, "tools/gate_promptops_policy.py"],
            "artifacts/promptops/gate_promptops_policy.json",
        ),
        GateStep("gate_promptops_perf", [py, "tools/gate_promptops_perf.py"], "artifacts/perf/gate_promptops_perf.json"),
        GateStep("gate_screen_schema", [py, "tools/gate_screen_schema.py"], "artifacts/phaseA/gate_screen_schema.json"),
        GateStep("gate_ledger", [py, "tools/gate_ledger.py"], None),
        GateStep("gate_deps_lock", [py, "tools/gate_deps_lock.py"], None),
        GateStep("gate_config_matrix", [py, "tools/gate_config_matrix.py"], "artifacts/config/gate_config_matrix.json"),
        GateStep("gate_static", [py, "tools/gate_static.py"], None),
        GateStep("gate_vuln", [py, "tools/gate_vuln.py"], None),
        GateStep("gate_doctor", [py, "tools/gate_doctor.py"], None),
        GateStep("gate_full_repo_miss_matrix", [py, "tools/gate_full_repo_miss_matrix.py", "--refresh"], None),
        GateStep("gate_acceptance_coverage", [py, "tools/gate_acceptance_coverage.py"], None),
        GateStep(
            "validate_blueprint_spec",
            [py, "tools/validate_blueprint_spec.py", "docs/spec/autocapture_nx_blueprint_2026-01-24.md"],
            None,
        ),
        GateStep("run_mod021_low_resource", ["bash", "tools/run_mod021_low_resource.sh"], None),
    ]
    return steps


def _extract_json_tail(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    if not text:
        return None
    start = text.rfind("{")
    while start >= 0:
        candidate = text[start:]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = text.rfind("{", 0, start)
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _matrix_semantic_issues(payload: dict[str, Any], *, path: str) -> list[str]:
    issues: list[str] = []
    has_matrix_shape = any(key in payload for key in ("matrix_total", "matrix_evaluated", "matrix_skipped", "matrix_failed"))
    if not has_matrix_shape:
        return issues
    matrix_evaluated = _coerce_int(payload.get("matrix_evaluated"))
    matrix_skipped = _coerce_int(payload.get("matrix_skipped"))
    matrix_failed = _coerce_int(payload.get("matrix_failed"))
    if matrix_evaluated is None:
        issues.append(f"{path}.matrix_evaluated=invalid")
    elif matrix_evaluated <= 0:
        issues.append(f"{path}.matrix_evaluated=0")
    if matrix_skipped is None:
        issues.append(f"{path}.matrix_skipped=invalid")
    elif matrix_skipped > 0:
        issues.append(f"{path}.matrix_skipped=nonzero")
    if matrix_failed is None:
        issues.append(f"{path}.matrix_failed=invalid")
    elif matrix_failed > 0:
        issues.append(f"{path}.matrix_failed=nonzero")
    matrix_total = _coerce_int(payload.get("matrix_total"))
    if matrix_total is not None and matrix_evaluated is not None and matrix_evaluated > matrix_total:
        issues.append(f"{path}.matrix_evaluated=gt_total")
    return issues


def _find_non_pass_markers(payload: Any, *, path: str = "root") -> list[str]:
    issues: list[str] = []
    if isinstance(payload, dict):
        issues.extend(_matrix_semantic_issues(payload, path=path))
        for key, value in payload.items():
            key_s = str(key).strip().lower()
            next_path = f"{path}.{key}"
            if key_s == "ok" and isinstance(value, bool) and not value:
                issues.append(f"{next_path}=false")
            if key_s in {"status", "state", "result"} and isinstance(value, str):
                state = value.strip().lower()
                if state in NON_PASS_STATUSES:
                    issues.append(f"{next_path}={state}")
                elif state not in PASS_STATUSES and state:
                    issues.append(f"{next_path}={state}")
            if key_s in {"warnings", "warning"} and isinstance(value, list) and len(value) > 0:
                issues.append(f"{next_path}=non_empty")
            issues.extend(_find_non_pass_markers(value, path=next_path))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            issues.extend(_find_non_pass_markers(item, path=f"{path}[{idx}]"))
    return issues


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return None
    return None


def _run_step(step: GateStep, root: Path, strict_status: bool) -> dict[str, Any]:
    t0 = time.perf_counter()
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(root))
    proc = subprocess.run(
        step.cmd,
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    stdout = str(proc.stdout or "")
    stderr = str(proc.stderr or "")
    artifact_payload = None
    artifact_path = None
    if step.artifact:
        artifact_path = str((root / step.artifact).resolve())
        artifact_payload = _read_json_file(root / step.artifact)
    stdout_json = _extract_json_tail(stdout)

    issues: list[str] = []
    if strict_status:
        if artifact_payload is not None:
            issues.extend(_find_non_pass_markers(artifact_payload, path="artifact"))
        if stdout_json is not None:
            issues.extend(_find_non_pass_markers(stdout_json, path="stdout_json"))
    ok = proc.returncode == 0 and len(issues) == 0
    return {
        "id": step.id,
        "cmd": step.cmd,
        "returncode": int(proc.returncode),
        "ok": bool(ok),
        "elapsed_ms": elapsed_ms,
        "artifact": artifact_path,
        "issues": issues,
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
    }


def run_release_gate(
    *,
    root: Path,
    strict_status: bool = True,
    max_steps: int = 0,
    start_step: int = 1,
) -> dict[str, Any]:
    py = str(root / ".venv" / "bin" / "python3")
    if not Path(py).exists():
        py = str(sys.executable)
    steps = _default_manifest(py)
    results: list[dict[str, Any]] = []
    failed_step: str | None = None
    start_idx = max(0, int(start_step) - 1)
    selected = steps[start_idx:]
    if int(max_steps) > 0:
        selected = selected[: int(max_steps)]
    limit = len(selected)
    for step in selected:
        row = _run_step(step, root, strict_status)
        results.append(row)
        if not bool(row.get("ok", False)):
            failed_step = str(step.id)
            break
    ok = failed_step is None
    return {
        "schema_version": 1,
        "ok": bool(ok),
        "strict_status": bool(strict_status),
        "failed_step": failed_step,
        "steps_total": len(steps),
        "start_step": int(start_idx + 1),
        "steps_planned_this_run": limit,
        "steps_executed": len(results),
        "steps": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fail-closed release gates.")
    parser.add_argument("--output", default="artifacts/release/release_gate_latest.json")
    parser.add_argument("--no-strict-status", action="store_true", default=False)
    parser.add_argument("--max-steps", type=int, default=0, help="Run only the first N steps (0=all).")
    parser.add_argument("--start-step", type=int, default=1, help="1-based index into manifest to begin execution.")
    args = parser.parse_args(argv)

    root = _repo_root()
    payload = run_release_gate(
        root=root,
        strict_status=not bool(args.no_strict_status),
        max_steps=int(args.max_steps),
        start_step=max(1, int(args.start_step)),
    )
    out = root / str(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(payload.get("ok", False)), "output": str(out)}, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
