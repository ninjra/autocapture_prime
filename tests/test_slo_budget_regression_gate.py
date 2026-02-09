import unittest

from autocapture_nx.ux.facade import compute_slo_summary


class SloBudgetRegressionGateTests(unittest.TestCase):
    def test_error_budget_used_exceeds_budget_is_detectable(self) -> None:
        config = {
            "performance": {
                "capture_lag_p95_ms": 10,
                "capture_queue_p95": 0,
                "capture_age_s": 1,
                "query_latency_ms": 10,
                "error_budget_pct": 1.0,
            }
        }
        # 100% of samples exceed threshold => 100% budget used.
        telemetry = {
            "history": {
                "capture": [
                    {"lag_ms": 9999, "queue_depth": 9999},
                    {"lag_ms": 9999, "queue_depth": 9999},
                ],
                "query": [{"latency_ms": 1}],
            }
        }
        slo = compute_slo_summary(config, telemetry, capture_status={"last_capture_age_seconds": 0.0}, processing_state={})
        used = slo.get("error_budget_used_pct")
        budget = slo.get("error_budget_pct")
        self.assertTrue(isinstance(used, float))
        self.assertTrue(isinstance(budget, float))
        self.assertGreater(used, budget)
        self.assertEqual(slo.get("overall"), "fail")


if __name__ == "__main__":
    unittest.main()

