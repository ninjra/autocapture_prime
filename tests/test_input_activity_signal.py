import time
import unittest
from datetime import datetime, timezone

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.input_windows.plugin import InputTrackerWindows


def _ctx() -> PluginContext:
    config = {
        "runtime": {"active_window_s": 3},
        "capture": {"input_tracking": {"store_derived": False}},
    }
    return PluginContext(config=config, get_capability=lambda _name: None, logger=lambda _msg: None)


class InputActivitySignalTests(unittest.TestCase):
    def test_activity_score_increases_on_event(self) -> None:
        tracker = InputTrackerWindows("test.input", _ctx())
        baseline = tracker.activity_signal()
        self.assertFalse(baseline["user_active"])

        ts = datetime.now(timezone.utc).isoformat()
        tracker._record_event("key", {"action": "press"}, ts)
        signal = tracker.activity_signal()

        self.assertTrue(signal["user_active"])
        self.assertGreater(signal["activity_score"], 0.0)
        self.assertGreater(signal["event_rate_hz"], 0.0)

    def test_activity_decays_after_idle(self) -> None:
        tracker = InputTrackerWindows("test.input", _ctx())
        ts = datetime.now(timezone.utc).isoformat()
        tracker._record_event("mouse", {"pressed": True}, ts)

        tracker._last_event_ts = time.time() - 10
        tracker._activity_events.clear()
        signal = tracker.activity_signal()

        self.assertFalse(signal["user_active"])
        self.assertLess(signal["activity_score"], 0.5)


if __name__ == "__main__":
    unittest.main()

