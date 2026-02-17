from __future__ import annotations

import unittest

from tools import gate_promptops_perf as mod


class GatePromptOpsPerfTests(unittest.TestCase):
    def test_percentile(self) -> None:
        self.assertEqual(mod._pct([10.0], 95.0), 10.0)
        self.assertEqual(mod._pct([0.0, 100.0], 50.0), 50.0)
        self.assertGreaterEqual(mod._pct([1.0, 2.0, 3.0], 95.0), 2.0)

    def test_regression_ok(self) -> None:
        self.assertTrue(mod._regression_ok(observed_ms=100.0, baseline_ms=100.0, max_regression_pct=0.10))
        self.assertTrue(mod._regression_ok(observed_ms=108.0, baseline_ms=100.0, max_regression_pct=0.10))
        self.assertFalse(mod._regression_ok(observed_ms=120.0, baseline_ms=100.0, max_regression_pct=0.10))
        self.assertTrue(
            mod._regression_ok(
                observed_ms=120.0,
                baseline_ms=100.0,
                max_regression_pct=0.10,
                jitter_ms=15.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
