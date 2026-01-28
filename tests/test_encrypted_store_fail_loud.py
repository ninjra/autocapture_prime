import json
import os
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_encrypted.plugin import EncryptedStoragePlugin, _encode_record_id


class EncryptedStoreFailLoudTests(unittest.TestCase):
    def test_metadata_decrypt_failure_raises_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "data_dir": tmp,
                    "encryption_required": True,
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                    "entity_map": {"persist": True},
                },
                "runtime": {"run_id": "run1", "timezone": "UTC"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = EncryptedStoragePlugin("test", ctx)
            store = plugin.capabilities()["storage.metadata"]
            ts_utc = "2026-01-26T00:00:00+00:00"
            store.put(
                "record1",
                {
                    "record_type": "derived.test",
                    "run_id": "run1",
                    "secret": "value",
                    "ts_utc": ts_utc,
                    "content_hash": "hash",
                },
            )

            safe_run = _encode_record_id("run1")
            safe_record = _encode_record_id("record1")
            path = os.path.join(
                tmp,
                "metadata",
                safe_run,
                "derived",
                "2026",
                "01",
                "26",
                f"{safe_record}.json",
            )
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            payload["ciphertext_b64"] = "corrupted"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)

            with self.assertRaises(RuntimeError):
                store.get("record1")


if __name__ == "__main__":
    unittest.main()
