import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture.research.runner import ResearchRunner


def _base_config(tmp: str) -> dict:
    return {
        "paths": {"data_dir": tmp},
        "storage": {"data_dir": tmp},
        "plugins": {"safe_mode": True, "allowlist": [], "enabled": {}, "default_pack": [], "search_paths": []},
        "research": {
            "cache_dir": str(Path(tmp) / "research" / "cache"),
            "enabled": True,
            "interval_s": 1,
            "report_dir": str(Path(tmp) / "research" / "reports"),
            "run_on_idle": True,
            "source_name": "default",
            "sources": [
                {"source_id": "local", "items": [{"title": "Alpha"}, {"title": "Beta"}]},
            ],
            "threshold_pct": 10,
            "watchlist": {"tags": ["alpha"]},
            "watchlist_name": "default",
        },
    }


class ResearchRunnerTests(unittest.TestCase):
    def test_run_once_emits_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            runner = ResearchRunner(config)
            result = runner.run_once()
            self.assertTrue(result.get("ok", False))
            reports = result.get("reports", [])
            self.assertTrue(reports)
            report_dir = Path(config["research"]["report_dir"])
            self.assertTrue(any(report_dir.iterdir()))

    def test_invalid_threshold_pct_is_clamped_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["research"]["threshold_pct"] = "abc"
            runner = ResearchRunner(config)
            result = runner.run_once()
            self.assertTrue(result.get("ok", False))
            self.assertAlmostEqual(float(result.get("threshold", 0.0)), 0.1, places=6)

    def test_plugin_error_is_surfaced_when_not_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            with mock.patch("autocapture.research.runner.PluginRegistry.load_plugins", side_effect=RuntimeError("boom")):
                runner = ResearchRunner(config)
                result = runner.run_once()
            self.assertTrue(result.get("ok", False))
            self.assertIn("plugin_error", result)

    def test_plugin_error_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["research"]["fail_closed_on_plugin_error"] = True
            with mock.patch("autocapture.research.runner.PluginRegistry.load_plugins", side_effect=RuntimeError("boom")):
                runner = ResearchRunner(config)
                result = runner.run_once()
            self.assertFalse(result.get("ok", True))
            self.assertEqual(result.get("reason"), "plugin_error")


if __name__ == "__main__":
    unittest.main()
