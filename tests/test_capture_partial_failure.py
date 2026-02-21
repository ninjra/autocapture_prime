import os
import tempfile
import unittest

from autocapture_nx.capture.pipeline import CapturePipeline, SegmentArtifact
from autocapture_nx.plugin_system.api import PluginContext


class _FailingMediaStore:
    def put_stream(self, _record_id: str, _stream, chunk_size: int = 1024 * 1024, *, ts_utc: str | None = None) -> None:
        _ = (chunk_size, ts_utc)
        raise RuntimeError("media write failed")


class _MetaStore:
    def __init__(self) -> None:
        self.data = {}

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def __init__(self) -> None:
        self.journal = []
        self.ledger = []

    def policy_snapshot_hash(self) -> str:
        return "policyhash"

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        self.journal.append((event_type, payload))
        return _kwargs.get("event_id") or "event_id"

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        _ = (inputs, outputs)
        self.ledger.append((stage, payload or {}))
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CapturePartialFailureTests(unittest.TestCase):
    def test_partial_failure_logged(self) -> None:
        media = _FailingMediaStore()
        meta = _MetaStore()
        event_builder = _EventBuilder()
        backpressure = _Backpressure()
        logger = _Logger()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "capture": {"video": {"backend": "mss", "segment_seconds": 60, "fps_target": 30, "container": "avi_mjpeg", "encoder": "cpu", "jpeg_quality": 90, "monitor_index": 0}},
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
                frame_source=iter(()),
            )
            path = os.path.join(tmpdir, "segment.bin")
            with open(path, "wb") as handle:
                handle.write(b"payload")
            artifact = SegmentArtifact(
                segment_id="run1/segment/0",
                path=path,
                frame_count=1,
                width=1,
                height=1,
                ts_start_utc="t0",
                ts_end_utc="t1",
                duration_ms=1000,
                fps_target=30,
                bitrate_kbps=8000,
                encoder="cpu",
                container_type="avi_mjpeg",
                container_ext="avi",
                encode_ms_total=1,
                encode_ms_max=1,
            )
            pipeline._write_segment(artifact, "mss")

        journal_events = [evt for evt, _payload in event_builder.journal]
        self.assertIn("capture.partial_failure", journal_events)
        ledger_events = [payload.get("event") for _stage, payload in event_builder.ledger]
        self.assertIn("capture.partial_failure", ledger_events)


if __name__ == "__main__":
    unittest.main()
