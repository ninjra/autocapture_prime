import unittest
from datetime import datetime, timezone

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.time_advanced.plugin import TimeIntentParser


class TimeParserTests(unittest.TestCase):
    def test_last_hours(self):
        config = {"time": {"timezone": "UTC", "dst_tie_breaker": "earliest", "relative_window_max_days": 30}}
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        parser = TimeIntentParser("test", ctx)
        now = datetime(2026, 1, 24, 12, 0, 0, tzinfo=timezone.utc)
        result = parser.parse("last 2 hours", now=now)
        self.assertEqual(result["time_window"]["end"], now.isoformat())

    def test_iso_date(self):
        config = {"time": {"timezone": "UTC", "dst_tie_breaker": "earliest", "relative_window_max_days": 30}}
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        parser = TimeIntentParser("test", ctx)
        result = parser.parse("2026-01-01")
        self.assertIsNotNone(result["time_window"])


if __name__ == "__main__":
    unittest.main()
