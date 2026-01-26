import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.input_windows.plugin import InputTrackerWindows


class _DummyEventBuilder:
    def __init__(self) -> None:
        self.calls = []

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        self.calls.append((event_type, payload))
        return "event-0"


class InputBatchingTests(unittest.TestCase):
    def test_input_events_batched_in_order(self) -> None:
        ctx = PluginContext(
            config={"capture": {"input_tracking": {"mode": "raw", "flush_interval_ms": 250}}},
            get_capability=lambda _k: None,
            logger=lambda _m: None,
        )
        tracker = InputTrackerWindows("input", ctx)
        builder = _DummyEventBuilder()
        tracker._event_builder = builder

        tracker._record_event("key", {"action": "press", "key": "a"}, "t1")
        tracker._record_event("mouse", {"button": "left", "pressed": True, "x": 1, "y": 2}, "t2")
        tracker._flush_batch()

        self.assertEqual(len(builder.calls), 1)
        event_type, payload = builder.calls[0]
        self.assertEqual(event_type, "input.batch")
        events = payload.get("events", [])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "key")
        self.assertEqual(events[1]["kind"], "mouse")
        counts = payload.get("counts", {})
        self.assertEqual(counts.get("key"), 1)
        self.assertEqual(counts.get("mouse"), 1)


if __name__ == "__main__":
    unittest.main()
