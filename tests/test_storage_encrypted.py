import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_encrypted.plugin import EncryptedStoragePlugin


class EncryptedStorageTests(unittest.TestCase):
    def test_encrypted_metadata_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "data_dir": tmp,
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                    "entity_map": {"persist": True},
                }
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = EncryptedStoragePlugin("test", ctx)
            store = plugin.capabilities()["storage.metadata"]
            store.put("record1", {"secret": "value"})
            path = Path(tmp) / "metadata" / "record1.json"
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("value", content)
            self.assertEqual(store.get("record1")["secret"], "value")


if __name__ == "__main__":
    unittest.main()
