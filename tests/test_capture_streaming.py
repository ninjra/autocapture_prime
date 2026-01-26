import os
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame
from plugins.builtin.capture_windows.plugin import CaptureWindows


class _MediaStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, bytes]] = []

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024) -> None:
        _ = chunk_size
        self.records.append((record_id, stream.read()))


class _MetaStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def __init__(self) -> None:
        self.journal = []
        self.ledger = []

    def journal_event(self, _event_type: str, payload: dict, **_kwargs) -> str:
        self.journal.append(payload)
        return "event_id"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        self.ledger.append(payload or {})
        return "hash"


class CaptureStreamingTests(unittest.TestCase):
    def test_segments_stream_to_media_store(self) -> None:
        media = _MediaStore()
        meta = _MetaStore()
        event_builder = _EventBuilder()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"storage": {"spool_dir": tmpdir}}
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = CaptureWindows("capture", ctx)
            run_id = "run1"
            segment = plugin._open_segment(tmpdir, run_id, 0)
            segment.add_frame(Frame(ts_utc="t0", data=b"x", width=1, height=1))
            plugin._flush_segment(segment, media, meta, event_builder)

            self.assertTrue(media.records)
            record_id, payload = media.records[0]
            self.assertEqual(record_id, "run1/segment/0")
            self.assertTrue(payload.startswith(b"PK"))
            self.assertIn("run1/segment/0", meta.data)
            self.assertEqual(meta.data["run1/segment/0"]["frame_count"], 1)
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "run1_segment_0.zip")))


if __name__ == "__main__":
    unittest.main()
