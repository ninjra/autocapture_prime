import unittest


class MetricsTtfrTests(unittest.TestCase):
    def test_metrics_includes_ttfr_and_plugin_timing(self) -> None:
        from autocapture.web.routes import metrics as metrics_mod

        metrics_mod.telemetry_snapshot = lambda: {  # type: ignore[assignment]
            "latest": {"foo": 1},
            "history": {"ttfr": [{"seconds": 1.25}, {"seconds": 2.5}]},
        }

        class _Facade:
            def plugins_timing(self):
                return {"ok": True, "rows": [], "events": 0}

        class _AppState:
            facade = _Facade()

        class _App:
            state = _AppState()

        class _Req:
            app = _App()

        payload = metrics_mod.metrics(_Req())  # type: ignore[arg-type]
        self.assertIn("ttfr_seconds", payload)
        self.assertIn("plugin_timing", payload)
        ttfr = payload["ttfr_seconds"]
        self.assertEqual(ttfr.get("samples"), 2)


if __name__ == "__main__":
    unittest.main()

