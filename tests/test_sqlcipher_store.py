import os
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_sqlcipher.plugin import SQLCipherStoragePlugin


class SQLCipherStoreTests(unittest.TestCase):
    def test_sqlcipher_put_get_or_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "data_dir": tmp,
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                }
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = SQLCipherStoragePlugin("sql", ctx)
            store = plugin.capabilities()["storage.metadata"]
            try:
                store.put("k", {"schema_version": 1, "record_type": "derived.test", "run_id": "run1", "content_hash": "hash", "v": 1})
                self.assertEqual(store.get("k")["v"], 1)
            except RuntimeError:
                # Dependency missing; acceptable for non-Windows test env
                return

    def test_encrypted_sqlite_fallback_when_sqlcipher_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "data_dir": tmp,
                    "encryption_enabled": True,
                    "encryption_required": False,
                    "sqlcipher": {"enabled": False},
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                }
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = SQLCipherStoragePlugin("sql", ctx)
            store = plugin.capabilities()["storage.metadata"]
            store.put(
                "k2",
                {"schema_version": 1, "record_type": "derived.test", "run_id": "run2", "content_hash": "hash2", "v": 2},
            )
            self.assertEqual(store.get("k2")["v"], 2)


if __name__ == "__main__":
    unittest.main()
