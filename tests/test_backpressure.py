import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.backpressure_basic.plugin import BackpressureController


class BackpressureTests(unittest.TestCase):
    def test_backpressure_reduces(self):
        config = {"backpressure": {"min_fps": 5, "max_fps": 30, "min_bitrate_kbps": 1000, "max_bitrate_kbps": 8000, "max_step_fps": 5, "max_step_bitrate_kbps": 1000, "hysteresis_s": 0, "max_queue_depth": 2}}
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        controller = BackpressureController("test", ctx)
        current = {"fps_target": 30, "bitrate_kbps": 8000}
        updated = controller.adjust({"queue_depth": 3, "now": 0}, current)
        self.assertEqual(updated["fps_target"], 25)
        self.assertEqual(updated["bitrate_kbps"], 7000)

    def test_backpressure_increases(self):
        config = {"backpressure": {"min_fps": 5, "max_fps": 30, "min_bitrate_kbps": 1000, "max_bitrate_kbps": 8000, "max_step_fps": 5, "max_step_bitrate_kbps": 1000, "hysteresis_s": 0, "max_queue_depth": 2}}
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        controller = BackpressureController("test", ctx)
        current = {"fps_target": 10, "bitrate_kbps": 2000}
        updated = controller.adjust({"queue_depth": 0, "now": 0}, current)
        self.assertEqual(updated["fps_target"], 15)
        self.assertEqual(updated["bitrate_kbps"], 3000)


if __name__ == "__main__":
    unittest.main()
