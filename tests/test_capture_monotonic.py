import tempfile
import unittest

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame


class _MediaStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, bytes]] = []

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024, *, ts_utc: str | None = None) -> None:
        _ = chunk_size
        _ = ts_utc
        self.records.append((record_id, stream.read()))


class _MetaStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def policy_snapshot_hash(self) -> str:
        return "policyhash"

    def journal_event(self, _event_type: str, _payload: dict, **_kwargs) -> str:
        return "event"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], **_kwargs) -> str:
        _ = (inputs, outputs)
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CaptureMonotonicTests(unittest.TestCase):
    def test_segment_duration_uses_monotonic(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"x", width=1, height=1, ts_monotonic=0.0),
            Frame(ts_utc="t1", data=b"y", width=1, height=1, ts_monotonic=6.0),
            Frame(ts_utc="t2", data=b"z", width=1, height=1, ts_monotonic=7.0),
        ]

        media = _MediaStore()
        meta = _MetaStore()
        event_builder = _EventBuilder()
        backpressure = _Backpressure()
        logger = _Logger()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "capture": {"video": {"backend": "mss", "segment_seconds": 5, "fps_target": 30, "container": "avi_mjpeg", "encoder": "cpu", "jpeg_quality": 90, "monitor_index": 0}},
                "storage": {"spool_dir": tmpdir, "data_dir": tmpdir},
                "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
                "runtime": {"run_id": "run1", "timezone": "UTC"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            pipeline = CapturePipeline(
                ctx.config,
                storage_media=media,
                storage_meta=meta,
                event_builder=event_builder,
                backpressure=backpressure,
                logger=logger,
                window_tracker=None,
                input_tracker=None,
                frame_source=iter(frames),
            )
            pipeline.start()
            pipeline.join()

        self.assertEqual(len(media.records), 2)
        self.assertEqual(media.records[0][0], "run1/segment/0")
        self.assertEqual(media.records[1][0], "run1/segment/1")


if __name__ == "__main__":
    unittest.main()
