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

    def test_safe_mode_forces_flag(self) -> None:
        paths = default_config_paths()
        cfg = load_config(paths, safe_mode=True)
        self.assertTrue(cfg.get("plugins", {}).get("safe_mode", False))


if __name__ == "__main__":
    unittest.main()
