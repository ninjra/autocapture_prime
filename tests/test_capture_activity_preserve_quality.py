import unittest
from unittest.mock import patch

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.capture.queues import BoundedQueue
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame


class _EventBuilder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        if event_type == "capture.activity":
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


class _InputTracker:
    def __init__(self) -> None:
        self.calls = 0

    def activity_signal(self) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"idle_seconds": 0.0, "user_active": True, "activity_score": 1.0}
        return {"idle_seconds": 10.0, "user_active": False, "activity_score": 0.0}


class CaptureActivityPreserveQualityTests(unittest.TestCase):
    def test_activity_does_not_reduce_quality_when_preserve_enabled(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"x", width=1, height=1, ts_monotonic=0.0),
            Frame(ts_utc="t1", data=b"y", width=1, height=1, ts_monotonic=1.0),
            Frame(ts_utc="t2", data=b"z", width=1, height=1, ts_monotonic=2.0),
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
                    "activity": {
                        "enabled": True,
                    "active_fps": 8,
                    "idle_fps": 30,
                    "active_jpeg_quality": 50,
                    "idle_jpeg_quality": 90,
                    "preserve_quality": True,
                    "check_interval_s": 0.2,
                },
            }
            },
            "storage": {"data_dir": ".", "disk_pressure": {"warn_free_gb": 200, "soft_free_gb": 150, "critical_free_gb": 100}},
            "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
            "runtime": {"run_id": "run1", "timezone": "UTC"},
        }
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        builder = _EventBuilder()
        pipeline = CapturePipeline(
            ctx.config,
            storage_media=None,
            storage_meta=None,
            event_builder=builder,
            backpressure=_Backpressure(),
            logger=_Logger(),
            window_tracker=None,
            input_tracker=_InputTracker(),
        )
        pipeline._frame_queue = BoundedQueue(5, "drop_oldest")

        monotonic_values = iter([0.0, 0.3, 0.6, 1.0, 1.4, 1.8])

        def fake_monotonic() -> float:
            return next(monotonic_values, 2.4)

        with patch("autocapture_nx.capture.pipeline._frame_iter", return_value=("mss", iter(frames))):
            with patch("autocapture_nx.capture.pipeline.time.monotonic", side_effect=fake_monotonic):
                pipeline._grab_loop()

        self.assertTrue(builder.events)
        qualities = [payload.get("jpeg_quality") for _event, payload in builder.events]
        self.assertTrue(all(q == 90 for q in qualities))


if __name__ == "__main__":
    unittest.main()
