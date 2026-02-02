import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.anomaly import AnomalyDetector


def _edge(edge_id: str, pred_error: float, ts_ms: int, model_version: str = "v1"):
    return {
        "edge_id": edge_id,
        "pred_error": pred_error,
        "provenance": {
            "created_ts_ms": ts_ms,
            "model_version": model_version,
        },
    }


class AnomalyDetectorTests(unittest.TestCase):
    def _detector(self, threshold: float, max_alerts: int = 25):
        config = {
            "processing": {
                "state_layer": {
                    "anomaly": {
                        "pred_error_threshold": threshold,
                        "max_alerts_per_run": max_alerts,
                    }
                }
            }
        }
        ctx = PluginContext(
            config=config,
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        return AnomalyDetector("test.anomaly", ctx)

    def test_threshold_filters_and_orders_alerts(self):
        detector = self._detector(0.5, max_alerts=10)
        edges = [
            _edge("e1", 0.6, 100),
            _edge("e2", 0.9, 200),
            _edge("e3", 0.55, 150),
            _edge("e4", 0.4, 50),
        ]
        alerts = detector.detect(edges)
        self.assertEqual([alert["edge_id"] for alert in alerts], ["e2", "e1", "e3"])
        self.assertTrue(all(alert["pred_error"] >= 0.5 for alert in alerts))

    def test_threshold_versions_alert_id(self):
        edge = _edge("e10", 0.9, 10)
        detector_a = self._detector(0.4)
        detector_b = self._detector(0.7)
        alert_a = detector_a.detect([edge])[0]["alert_id"]
        alert_b = detector_b.detect([edge])[0]["alert_id"]
        self.assertNotEqual(alert_a, alert_b)


if __name__ == "__main__":
    unittest.main()
