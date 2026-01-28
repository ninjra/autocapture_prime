import unittest
from unittest.mock import patch

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.capture.queues import BoundedQueue
from autocapture_nx.windows.win_capture import Frame


class _EventBuilder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        if event_type == "telemetry.capture":
            self.events.append((event_type, payload))
        return "event"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], **_kwargs) -> str:
        _ = (inputs, outputs)
        return "hash"

    def policy_snapshot_hash(self) -> str:
        return "policyhash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CaptureTelemetryTests(unittest.TestCase):
    def test_capture_telemetry_emits_queue_and_cpu(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"x", width=1, height=1, ts_monotonic=0.0),
            Frame(ts_utc="t1", data=b"y", width=1, height=1, ts_monotonic=0.6),
            Frame(ts_utc="t2", data=b"z", width=1, height=1, ts_monotonic=1.2),
        ]
        config = {
            "capture": {
                "video": {
                    "backend": "mss",
                    "segment_seconds": 60,
                    "fps_target": 30,
                    "container": "avi_mjpeg",
                    "encoder": "cpu",
                    "jpeg_quality": 90,
                    "monitor_index": 0,
                    "activity": {"enabled": False},
                }
            },
            "runtime": {"run_id": "run1", "telemetry": {"enabled": True, "emit_interval_s": 1}},
            "storage": {"data_dir": ".", "disk_pressure": {"warn_free_gb": 200, "soft_free_gb": 150, "critical_free_gb": 100}},
            "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
        }
        builder = _EventBuilder()
        pipeline = CapturePipeline(
            config,
            storage_media=None,
            storage_meta=None,
            event_builder=builder,
            backpressure=_Backpressure(),
            logger=_Logger(),
            window_tracker=None,
            input_tracker=None,
            governor=None,
        )
        pipeline._frame_queue = BoundedQueue(5, "drop_oldest")

        mono_state = {"value": 0.0}
        cpu_state = {"value": 0.0}

        def fake_monotonic() -> float:
            mono_state["value"] += 0.6
            return mono_state["value"]

        def fake_process_time() -> float:
            cpu_state["value"] += 0.05
            return cpu_state["value"]

        with patch("autocapture_nx.capture.pipeline._frame_iter", return_value=("mss", iter(frames))):
            with patch("autocapture_nx.capture.pipeline.time.monotonic", side_effect=fake_monotonic):
                with patch("autocapture_nx.capture.pipeline.time.process_time", side_effect=fake_process_time):
                    pipeline._grab_loop()

        self.assertTrue(builder.events)
        _event, payload = builder.events[-1]
        for key in ("queue_depth", "drops_total", "lag_ms", "cpu_pct"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
