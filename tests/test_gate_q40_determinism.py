from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_module():
    path = Path("tools/gate_q40_determinism.py")
    spec = importlib.util.spec_from_file_location("gate_q40_determinism_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateQ40DeterminismTests(unittest.TestCase):
    def test_evaluate_runs_passes_for_stable_success(self) -> None:
        mod = _load_module()
        rows = [
            {"ok": True, "signature": "abc"},
            {"ok": True, "signature": "abc"},
            {"ok": True, "signature": "abc"},
            {"ok": True, "signature": "abc"},
            {"ok": True, "signature": "abc"},
        ]
        out = mod.evaluate_runs(rows)
        self.assertTrue(out["ok"])
        self.assertEqual(out["unique_signature_count"], 1)

    def test_evaluate_runs_fails_on_signature_drift(self) -> None:
        mod = _load_module()
        rows = [
            {"ok": True, "signature": "a"},
            {"ok": True, "signature": "b"},
        ]
        out = mod.evaluate_runs(rows)
        self.assertFalse(out["ok"])
        self.assertEqual(out["unique_signature_count"], 2)

    def test_strict_semantics_enforced(self) -> None:
        mod = _load_module()
        ok, reasons = mod._strict_semantics_ok(
            {
                "ok": True,
                "matrix_evaluated": 39,
                "matrix_failed": 1,
                "matrix_skipped": 0,
            }
        )
        self.assertFalse(ok)
        self.assertIn("matrix_evaluated_not_40", reasons)
        self.assertIn("matrix_failed_nonzero", reasons)


if __name__ == "__main__":
    unittest.main()
