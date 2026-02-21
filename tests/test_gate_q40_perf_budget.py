from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_module():
    path = Path("tools/gate_q40_perf_budget.py")
    spec = importlib.util.spec_from_file_location("gate_q40_perf_budget_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateQ40PerfBudgetTests(unittest.TestCase):
    def test_evaluate_perf_budget_passes_when_all_constraints_met(self) -> None:
        mod = _load_module()
        ok, reasons = mod.evaluate_perf_budget(
            runtime_s=120.0,
            matrix={"ok": True, "matrix_evaluated": 40, "matrix_failed": 0, "matrix_skipped": 0},
            report={"idle": {"steps_taken": 10, "budget_ms": 180000}, "uia_docs": {"total": 3}},
            max_runtime_s=300.0,
            max_idle_steps=24,
            max_budget_ms=240000,
        )
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_evaluate_perf_budget_fails_with_multiple_reasons(self) -> None:
        mod = _load_module()
        ok, reasons = mod.evaluate_perf_budget(
            runtime_s=600.0,
            matrix={"ok": False, "matrix_evaluated": 39, "matrix_failed": 1, "matrix_skipped": 1},
            report={"idle": {"steps_taken": 30, "budget_ms": 300000}, "uia_docs": {"total": 0}},
            max_runtime_s=300.0,
            max_idle_steps=24,
            max_budget_ms=240000,
        )
        self.assertFalse(ok)
        self.assertIn("runtime_exceeds_budget", reasons)
        self.assertIn("matrix_not_ok", reasons)
        self.assertIn("matrix_evaluated_not_40", reasons)
        self.assertIn("matrix_failed_nonzero", reasons)
        self.assertIn("matrix_skipped_nonzero", reasons)
        self.assertIn("idle_steps_exceed_budget", reasons)
        self.assertIn("idle_budget_ms_exceed_limit", reasons)
        self.assertIn("uia_docs_missing", reasons)


if __name__ == "__main__":
    unittest.main()
