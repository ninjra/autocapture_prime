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
        return _kwargs.get("event_id") or "event_id"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], **_kwargs) -> str:
        _ = (inputs, outputs)
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CaptureResolutionBoundaryTests(unittest.TestCase):
    def test_segment_splits_on_resolution_change(self) -> None:
        media = _MediaStore()
        meta = _MetaStore()
        event_builder = _EventBuilder()
        backpressure = _Backpressure()
        logger = _Logger()

        frames = [
            Frame(ts_utc="t0", data=b"a", width=64, height=64, ts_monotonic=0.0),
            Frame(ts_utc="t1", data=b"b", width=128, height=64, ts_monotonic=0.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "capture": {
                    "video": {
                        "backend": "mss",
                        "segment_seconds": 120,
                        "fps_target": 120,
                        "container": "avi_mjpeg",
                        "encoder": "cpu",
                        "jpeg_quality": 90,
                        "monitor_index": 0,
                        "dedupe": {"enabled": False},
                        "activity": {"enabled": False},
                    }
                },
                "storage": {"spool_dir": tmpdir, "data_dir": tmpdir},
                "backpressure": {"max_fps": 120, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
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

        self.assertEqual(len(meta.data), 2)
        widths = sorted([payload.get("width") for payload in meta.data.values()])
        self.assertEqual(widths, [64, 128])


if __name__ == "__main__":
    unittest.main()
