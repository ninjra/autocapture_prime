import unittest

from tools.gate_perf import _evaluate_regression


class PerfRegressionTests(unittest.TestCase):
    def test_regression_threshold(self) -> None:
        baseline = {"artifacts_per_s": 100.0}
        self.assertTrue(_evaluate_regression({"artifacts_per_s": 90.0}, baseline, 0.25))
        self.assertFalse(_evaluate_regression({"artifacts_per_s": 60.0}, baseline, 0.25))

    def test_missing_baseline_passes(self) -> None:
        self.assertTrue(_evaluate_regression({"artifacts_per_s": 0.0}, {}, 0.25))


if __name__ == "__main__":
    unittest.main()
