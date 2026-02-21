import unittest

from autocapture_nx.kernel.config import _apply_capture_preset


class CapturePresetTests(unittest.TestCase):
    def test_apply_capture_preset_merges_patch(self) -> None:
        config = {
            "capture": {
                "mode_preset": "memory_replacement_raw",
                "presets": {
                    "memory_replacement_raw": {
                        "capture": {
                            "screenshot": {"fps_target": 2},
                            "diff_epsilon": 0,
                        }
                    }
                },
            }
        }
        merged = _apply_capture_preset(config)
        self.assertEqual(merged["capture"]["screenshot"]["fps_target"], 2)
        self.assertEqual(merged["capture"]["diff_epsilon"], 0)

    def test_apply_capture_preset_noop_when_missing(self) -> None:
        config = {"capture": {"mode_preset": "missing", "presets": {}}}
        merged = _apply_capture_preset(config)
        self.assertEqual(merged, config)


if __name__ == "__main__":
    unittest.main()
