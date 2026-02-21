import unittest
from unittest.mock import patch

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.capture.queues import BoundedQueue
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame


class _EventBuilder:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.ledger_events: list[str] = []

    def journal_event(self, event_type: str, _payload: dict, **_kwargs) -> str:
        self.events.append(event_type)
        return "event"

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        _ = (inputs, outputs)
        if isinstance(payload, dict):
            self.ledger_events.append(payload.get("event", stage))
        else:
            self.ledger_events.append(stage)
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CaptureDiskPressureTests(unittest.TestCase):
    def test_disk_pressure_degrades_capture(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"x", width=1, height=1, ts_monotonic=0.0),
            Frame(ts_utc="t1", data=b"y", width=1, height=1, ts_monotonic=1.0),
        ]
        config = {
            "capture": {"video": {"backend": "mss", "segment_seconds": 60, "fps_target": 30, "container": "avi_mjpeg", "encoder": "cpu", "jpeg_quality": 90, "monitor_index": 0}},
            "storage": {"data_dir": ".", "disk_pressure": {"warn_free_gb": 200, "soft_free_gb": 150, "critical_free_gb": 100}},
            "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5, "min_fps": 5, "min_bitrate_kbps": 1000},
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
            input_tracker=None,
        )
        pipeline._frame_queue = BoundedQueue(5, "drop_oldest")

        with patch("autocapture_nx.capture.pipeline._frame_iter", return_value=("mss", iter(frames))):
            with patch("autocapture_nx.capture.pipeline._free_bytes", return_value=120 * 1024 ** 3):
                monotonic_values = iter([0.0, 2.0, 4.0, 6.0, 8.0])

                def fake_monotonic() -> float:
                    return next(monotonic_values, 10.0)

                with patch("autocapture_nx.capture.pipeline.time.monotonic", side_effect=fake_monotonic):
                    pipeline._grab_loop()

        self.assertIn("capture.degrade", builder.events)
        self.assertIn("capture.degrade", builder.ledger_events)


if __name__ == "__main__":
    unittest.main()
