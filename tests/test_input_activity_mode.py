import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.input_windows.plugin import InputTrackerWindows, _InputBatcher


class _MediaStore:
    def __init__(self) -> None:
        self.records: dict[str, bytes] = {}

    def put(self, key: str, value: bytes, **_kwargs) -> None:
        self.records[key] = value

    def put_new(self, key: str, value: bytes, **_kwargs) -> None:
        self.records[key] = value


class _MetaStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value

    def put_new(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        self.calls.append((event_type, payload))
        return "event-0"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], **_kwargs) -> str:
        _ = (inputs, outputs)
        return "hash"


class InputActivityModeTests(unittest.TestCase):
    def test_activity_mode_summarizes_without_raw_events(self) -> None:
        media = _MediaStore()
        meta = _MetaStore()
        builder = _EventBuilder()
        stores = {"storage.media": media, "storage.metadata": meta}
        config = {
            "runtime": {"run_id": "run1"},
            "capture": {"input_tracking": {"mode": "activity", "flush_interval_ms": 250, "store_derived": True}},
        }
        ctx = PluginContext(config=config, get_capability=lambda name: stores[name], logger=lambda _m: None)
        tracker = InputTrackerWindows("input", ctx)
        tracker._event_builder = builder
        tracker._mode = "activity"
        tracker._batcher = _InputBatcher(store_events=False)

        tracker._record_event("key", {"action": "press", "key": "A"}, "t1")
        tracker._record_event("mouse", {"button": "left", "pressed": True, "x": 10, "y": 20}, "t2")
        tracker._flush_batch()

        self.assertEqual(len(builder.calls), 1)
        event_type, payload = builder.calls[0]
        self.assertEqual(event_type, "input.batch")
        self.assertEqual(payload.get("events", []), [])
        self.assertEqual(payload.get("counts", {}).get("key"), 1)
        self.assertEqual(payload.get("counts", {}).get("mouse"), 1)
        self.assertEqual(payload.get("event_count"), 2)
        self.assertEqual(payload.get("mode"), "activity")

        self.assertEqual(len(meta.data), 1)
        summary = next(iter(meta.data.values()))
        self.assertEqual(summary.get("event_count"), 2)
        self.assertEqual(summary.get("counts", {}).get("key"), 1)
        self.assertEqual(summary.get("counts", {}).get("mouse"), 1)
        self.assertEqual(summary.get("mode"), "activity")
        self.assertNotIn("log_id", summary)


if __name__ == "__main__":
    unittest.main()
