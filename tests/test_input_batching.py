import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.input_windows.plugin import InputTrackerWindows, _decode_input_log, _encode_input_log


class _DummyEventBuilder:
    def __init__(self) -> None:
        self.calls = []

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        self.calls.append((event_type, payload))
        return "event-0"


class _DummyEventBuilderFull(_DummyEventBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.ledger = []

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        self.ledger.append((stage, inputs, outputs, payload))
        return "hash"


class _MediaStore:
    def __init__(self) -> None:
        self.data = {}

    def put_new(self, record_id: str, payload: bytes, **_kwargs) -> None:
        self.data[record_id] = payload

    def put(self, record_id: str, payload: bytes, **_kwargs) -> None:
        self.data[record_id] = payload


class _MetaStore:
    def __init__(self) -> None:
        self.data = {}

    def put_new(self, record_id: str, payload: dict, **_kwargs) -> None:
        self.data[record_id] = payload

    def put(self, record_id: str, payload: dict, **_kwargs) -> None:
        self.data[record_id] = payload


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

    def test_input_log_encoding_has_header(self) -> None:
        encoded = _encode_input_log([{"kind": "key", "ts_utc": "t1"}])
        self.assertTrue(encoded.startswith(b"INPT1"))

    def test_input_log_roundtrip_and_summary(self) -> None:
        media = _MediaStore()
        meta = _MetaStore()
        ctx = PluginContext(
            config={"runtime": {"run_id": "run1"}, "capture": {"input_tracking": {"mode": "raw", "store_derived": True}}},
            get_capability=lambda name: media if name == "storage.media" else (meta if name == "storage.metadata" else None),
            logger=lambda _m: None,
        )
        tracker = InputTrackerWindows("input", ctx)
        builder = _DummyEventBuilderFull()
        tracker._event_builder = builder

        tracker._record_event("key", {"action": "press", "key": "a"}, "2024-01-01T00:00:00+00:00")
        tracker._record_event("mouse", {"button": "left", "pressed": True, "x": 1, "y": 2}, "2024-01-01T00:00:01+00:00")
        tracker._flush_batch()

        log_id = "run1/derived.input.log/0"
        summary_id = "run1/derived.input.summary/0"
        self.assertIn(log_id, media.data)
        decoded = _decode_input_log(media.data[log_id])
        self.assertEqual(len(decoded), 2)
        self.assertEqual(decoded[0]["kind"], "key")
        self.assertIn(summary_id, meta.data)
        summary = meta.data[summary_id]
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["counts"]["key"], 1)
        self.assertEqual(summary["counts"]["mouse"], 1)


if __name__ == "__main__":
    unittest.main()
