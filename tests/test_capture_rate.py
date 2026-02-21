import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame, iter_screenshots
from plugins.builtin.backpressure_basic.plugin import BackpressureController


class CaptureRateTests(unittest.TestCase):
    def test_backpressure_changes_interval(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"x", width=1, height=1),
            Frame(ts_utc="t1", data=b"y", width=1, height=1),
        ]
        sleep_calls = []

        def sleep_fn(dt: float) -> None:
            sleep_calls.append(dt)

        def now_fn() -> float:
            return 0.0

        config = {"backpressure": {"min_fps": 5, "max_fps": 30, "min_bitrate_kbps": 1000, "max_bitrate_kbps": 8000, "max_step_fps": 5, "max_step_bitrate_kbps": 1000, "hysteresis_s": 0, "max_queue_depth": 1}}
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        controller = BackpressureController("bp", ctx)

        state = {"fps": 30, "bitrate": 8000, "call": 0}
        queue_depths = [0, 10]

        def fps_provider() -> int:
            idx = min(state["call"], len(queue_depths) - 1)
            update = controller.adjust(
                {"queue_depth": queue_depths[idx], "now": 0},
                {"fps_target": state["fps"], "bitrate_kbps": state["bitrate"]},
            )
            state["fps"] = update["fps_target"]
            state["bitrate"] = update["bitrate_kbps"]
            state["call"] += 1
            return state["fps"]

        list(iter_screenshots(fps_provider, frame_source=iter(frames), now_fn=now_fn, sleep_fn=sleep_fn))

        self.assertGreaterEqual(len(sleep_calls), 2)
        self.assertEqual(state["fps"], 25)
        self.assertGreater(sleep_calls[1], sleep_calls[0])


if __name__ == "__main__":
    unittest.main()
