"""Gate: Phase 5 scheduler / governor checks."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _run_suite(module: str) -> tuple[str, dict]:
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=1)
    result = runner.run(suite)
    status = "pass"
    skip_reason = None
    if result.failures or result.errors:
        status = "fail"
    elif result.testsRun > 0 and len(result.skipped) == result.testsRun:
        status = "skip"
        skip_reason = "; ".join(reason for _test, reason in result.skipped)
    return status, {
        "name": module,
        "status": status,
        "skipped": len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skip_reason": skip_reason,
    }


def main() -> int:
    checks = [
        "tests.test_runtime_conductor",
        "tests.test_runtime_budgets",
        "tests.test_resource_budgets",
        "tests.test_resource_budget_enforcement",
        "tests.test_idle_processor",
        "tests.test_idle_processor_chunking",
        "tests.test_idle_multi_extractors",
        "tests.test_idle_sst_pipeline",
        "tests.test_governor_gating",
        "tests.test_work_leases",
        "tests.test_input_activity_mode",
        "tests.test_fullscreen_halt",
        "tests.test_tier_planner_escalation",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase5"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase5.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
