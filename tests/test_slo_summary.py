import unittest

from autocapture_nx.ux.facade import compute_slo_summary


class SloSummaryTests(unittest.TestCase):
    def test_slo_summary_flags_failure(self) -> None:
        config = {
            "performance": {
                "capture_lag_p95_ms": 1000,
                "capture_queue_p95": 3,
                "capture_age_s": 10,
                "error_budget_pct": 1.0,
                "startup_ms": 1,
                "query_latency_ms": 500,
                "ingestion_mb_s": 1,
                "memory_ceiling_mb": 1,
            }
        }
        telemetry = {
            "history": {
                "capture": [
                    {"lag_ms": 1500, "queue_depth": 1},
                    {"lag_ms": 2000, "queue_depth": 2},
                ],
                "query": [{"latency_ms": 200}],
            }
        }
        capture_status = {"last_capture_age_seconds": 5}
        processing_state = {"watchdog": {"state": "ok"}}
        summary = compute_slo_summary(config, telemetry, capture_status, processing_state)
        self.assertEqual(summary["capture"]["status"], "fail")
        self.assertEqual(summary["overall"], "fail")
        self.assertGreater(summary["error_budget_used_pct"], 0)
        self.assertEqual(summary["query"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
