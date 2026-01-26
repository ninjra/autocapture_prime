import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
