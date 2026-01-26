import unittest

from autocapture.config.defaults import default_config_paths
from autocapture.config.load import load_config


class TestConfigDefaults(unittest.TestCase):
    def test_defaults_are_safe(self) -> None:
        paths = default_config_paths()
        cfg = load_config(paths, safe_mode=False)
        privacy = cfg.get("privacy", {})
        cloud = privacy.get("cloud", {})
        egress = privacy.get("egress", {})
        self.assertFalse(cloud.get("enabled", True))
        self.assertFalse(cloud.get("allow_images", True))
        self.assertTrue(egress.get("default_sanitize", False))
        self.assertFalse(egress.get("allow_raw_egress", True))
        self.assertTrue(egress.get("reasoning_packet_only", False))
        self.assertTrue(cfg.get("storage", {}).get("encryption_required", False))
        on_query = cfg.get("processing", {}).get("on_query", {})
        self.assertFalse(on_query.get("allow_decode_extract", True))
        cursor_cfg = cfg.get("capture", {}).get("cursor", {})
        self.assertFalse(cursor_cfg.get("enabled", True))

    def test_safe_mode_forces_flag(self) -> None:
        paths = default_config_paths()
        cfg = load_config(paths, safe_mode=True)
        self.assertTrue(cfg.get("plugins", {}).get("safe_mode", False))


if __name__ == "__main__":
    unittest.main()
