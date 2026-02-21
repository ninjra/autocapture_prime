from __future__ import annotations

from pathlib import Path
import unittest

from autocapture_prime.config import load_prime_config


class AutocapturePrimeConfigSchemaTests(unittest.TestCase):
    def test_required_fields_load(self) -> None:
        cfg = load_prime_config("config/autocapture_prime.yaml")
        self.assertEqual(cfg.api_host, "127.0.0.1")
        self.assertGreater(cfg.api_port, 0)
        self.assertTrue(str(cfg.vllm_base_url).startswith("http://127.0.0.1"))
        self.assertGreaterEqual(cfg.top_k_frames, 1)
        self.assertIsInstance(cfg.allow_mm_embeds, bool)
        self.assertFalse(cfg.allow_mm_embeds)
        self.assertFalse(cfg.allow_agpl)
        self.assertFalse(cfg.trust_remote_code)

    def test_example_config_loads(self) -> None:
        cfg = load_prime_config("config/example.autocapture_prime.yaml")
        self.assertIsInstance(cfg.storage_root, Path)
        self.assertIsInstance(cfg.spool_root, Path)


if __name__ == "__main__":
    unittest.main()
