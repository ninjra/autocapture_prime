import os
import tempfile
import unittest

from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.egress_sanitizer.plugin import EgressSanitizer


class TokenizerVersioningTests(unittest.TestCase):
    def test_tokenizer_key_id_and_version_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            keyring_path = os.path.join(tmp, "vault", "keyring.json")
            root_key_path = os.path.join(tmp, "vault", "root.key")
            config = {
                "storage": {
                    "data_dir": tmp,
                    "crypto": {"keyring_path": keyring_path, "root_key_path": root_key_path},
                    "encryption_required": False,
                },
                "privacy": {"egress": {"token_scope": "default"}},
            }
            KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=False)
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            sanitizer = EgressSanitizer("sanitizer", ctx)
            payload = {"query": "Email john@example.com"}
            result1 = sanitizer.sanitize_payload(payload)
            meta1 = result1.get("_tokenizer", {})
            token1 = next(iter(result1.get("_tokens", {}) or {}), None)
            self.assertIsNotNone(token1)
            self.assertIn("key_id", meta1)
            self.assertIn("key_version", meta1)

            result1b = sanitizer.sanitize_payload(payload)
            token1b = next(iter(result1b.get("_tokens", {}) or {}), None)
            self.assertEqual(token1, token1b)

            keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=False)
            keyring.rotate("entity_tokens")
            sanitizer2 = EgressSanitizer("sanitizer", ctx)
            result2 = sanitizer2.sanitize_payload(payload)
            meta2 = result2.get("_tokenizer", {})
            token2 = next(iter(result2.get("_tokens", {}) or {}), None)
            self.assertNotEqual(meta1.get("key_id"), meta2.get("key_id"))
            self.assertNotEqual(meta1.get("key_version"), meta2.get("key_version"))
            self.assertNotEqual(token1, token2)


if __name__ == "__main__":
    unittest.main()
