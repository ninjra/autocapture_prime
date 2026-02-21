import json
import unittest


class DefaultConfigDisablesVideoTests(unittest.TestCase):
    def test_default_config_disables_video_capture(self) -> None:
        with open("config/default.json", "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        enabled = bool(cfg.get("capture", {}).get("video", {}).get("enabled", True))
        self.assertFalse(enabled)


if __name__ == "__main__":
    unittest.main()
