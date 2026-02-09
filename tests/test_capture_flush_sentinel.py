import tempfile
import threading
import unittest

from autocapture_nx.capture.pipeline import CapturePipeline, FLUSH_SENTINEL, STOP_SENTINEL
from autocapture_nx.capture.queues import BoundedQueue
from autocapture_nx.windows.win_capture import Frame


class CaptureFlushSentinelTests(unittest.TestCase):
    def test_flush_sentinel_seals_partial_segment(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"jpeg0", width=2, height=2, ts_monotonic=0.0),
            Frame(ts_utc="t1", data=b"jpeg1", width=2, height=2, ts_monotonic=0.1),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "capture": {
                    "video": {
                        "enabled": True,
                        "backend": "mss",
                        "container": "zip",
                        "encoder": "cpu",
                        "segment_seconds": 60,
                        "fps_target": 30,
                        "jpeg_quality": 90,
                        "frame_format": "jpeg",
                        "include_cursor": False,
                        "include_cursor_shape": False,
                        "monitor_index": 0,
                        "resolution": "native",
                        "activity": {"enabled": False},
                    }
                },
                "runtime": {"run_id": "run1", "telemetry": {"enabled": False, "emit_interval_s": 5}},
                "storage": {"data_dir": ".", "spool_dir": tmpdir, "disk_pressure": {"warn_free_gb": 200, "soft_free_gb": 150, "critical_free_gb": 100}},
                "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
            }
            pipeline = CapturePipeline(
                config,
                storage_media=None,
                storage_meta=None,
                event_builder=None,
                backpressure=None,
                logger=None,
                window_tracker=None,
                input_tracker=None,
            )
            pipeline._frame_queue = BoundedQueue(8, "drop_oldest")
            pipeline._segment_queue = BoundedQueue(8, "block")
            pipeline._backend_used = "mss"

            t = threading.Thread(target=pipeline._encode_loop, daemon=True)
            t.start()

            for frame in frames:
                pipeline._frame_queue.put(frame)
            pipeline._frame_queue.put(FLUSH_SENTINEL)
            pipeline._frame_queue.put(STOP_SENTINEL)

            first = pipeline._segment_queue.get(timeout=2.0)
            self.assertIsNotNone(first)
            self.assertIsNot(first, STOP_SENTINEL)
            artifact, _backend = first
            self.assertTrue(artifact.path.endswith(".zip"))

            second = pipeline._segment_queue.get(timeout=2.0)
            self.assertIs(second, STOP_SENTINEL)

            t.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()

