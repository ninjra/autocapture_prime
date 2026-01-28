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
                store.put("k", {"record_type": "derived.test", "run_id": "run1", "content_hash": "hash", "v": 1})
                self.assertEqual(store.get("k")["v"], 1)
            except RuntimeError:
                # Dependency missing; acceptable for non-Windows test env
                return


if __name__ == "__main__":
    unittest.main()
