import tempfile
import unittest

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame


class _MediaStore:
    def __init__(self) -> None:
        self.records = []

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024) -> None:
        _ = chunk_size
        self.records.append((record_id, stream.read()))


class _MetaStore:
    def __init__(self) -> None:
        self.data = {}

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def policy_snapshot_hash(self) -> str:
        return "policyhash"

    def journal_event(self, _event_type: str, _payload: dict, **_kwargs) -> str:
        return _kwargs.get("event_id") or "event"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], **_kwargs) -> str:
        _ = (inputs, outputs)
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class _WindowTracker:
    def last_record(self) -> dict:
        return {"record_id": "run1/window/0", "ts_utc": "t0", "window": {"title": "Title"}}


class _InputTracker:
    def snapshot(self, reset: bool = False) -> dict:
        _ = reset
        return {"counts": {"key": 1, "mouse": 2}, "last_event_id": "run1/input/0", "last_ts_utc": "t0"}


class CaptureWindowInputRefsTests(unittest.TestCase):
    def test_segment_includes_window_and_input_refs(self) -> None:
        frames = [Frame(ts_utc="t0", data=b"x", width=1, height=1, ts_monotonic=0.0)]
        media = _MediaStore()
        meta = _MetaStore()
        builder = _EventBuilder()
        backpressure = _Backpressure()
        logger = _Logger()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "capture": {"video": {"backend": "mss", "segment_seconds": 1, "fps_target": 30, "container": "avi_mjpeg", "encoder": "cpu", "jpeg_quality": 90, "monitor_index": 0}},
                "storage": {"spool_dir": tmpdir, "data_dir": tmpdir},
                "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
                "runtime": {"run_id": "run1", "timezone": "UTC"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            pipeline = CapturePipeline(
                ctx.config,
                storage_media=media,
                storage_meta=meta,
                event_builder=builder,
                backpressure=backpressure,
                logger=logger,
                window_tracker=_WindowTracker(),
                input_tracker=_InputTracker(),
                frame_source=iter(frames),
            )
            pipeline.start()
            pipeline.join()

        record = meta.data.get("run1/segment/0")
        self.assertIsNotNone(record)
        self.assertIn("window_ref", record)
        self.assertIn("input_ref", record)
        self.assertEqual(record["window_ref"]["record_id"], "run1/window/0")
        self.assertEqual(record["input_ref"]["last_event_id"], "run1/input/0")


if __name__ == "__main__":
    unittest.main()
