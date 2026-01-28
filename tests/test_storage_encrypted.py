import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_encrypted.plugin import (
    BLOB_MAGIC,
    STREAM_MAGIC,
    EncryptedStoragePlugin,
    _encode_record_id,
)


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
                },
                "runtime": {"run_id": "run1"},
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
            path = (
                Path(tmp)
                / "metadata"
                / safe_run
                / "derived"
                / "2026"
                / "01"
                / "26"
                / f"{safe_record}.json"
            )
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("value", content)
            self.assertEqual(store.get("record1")["secret"], "value")

    def test_metadata_keys_sorted(self) -> None:
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
            plugin = EncryptedStoragePlugin("test", ctx)
            store = plugin.capabilities()["storage.metadata"]
            store.put("b", {"record_type": "derived.test", "run_id": "run1", "content_hash": "hash", "value": 2})
            store.put("a", {"record_type": "derived.test", "run_id": "run1", "content_hash": "hash", "value": 1})
            self.assertEqual(store.keys(), ["a", "b"])

    def test_media_blob_binary_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "data_dir": tmp,
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                },
                "runtime": {"run_id": "run1"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = EncryptedStoragePlugin("test", ctx)
            media = plugin.capabilities()["storage.media"]
            ts_utc = "2026-01-26T00:00:00+00:00"
            media.put("media/1", b"hello-world", ts_utc=ts_utc)
            safe_run = _encode_record_id("run1")
            safe_record = _encode_record_id("media/1")
            path = (
                Path(tmp)
                / "media"
                / safe_run
                / "evidence"
                / "2026"
                / "01"
                / "26"
                / f"{safe_record}.blob"
            )
            self.assertTrue(path.exists())
            payload = path.read_bytes()
            self.assertTrue(payload.startswith(BLOB_MAGIC))
            self.assertNotIn(b"hello-world", payload)
            self.assertEqual(media.get("media/1"), b"hello-world")
            self.assertIn("media/1", media.keys())

    def test_media_stream_binary_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {
                    "data_dir": tmp,
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                },
                "runtime": {"run_id": "run1"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = EncryptedStoragePlugin("test", ctx)
            media = plugin.capabilities()["storage.media"]
            ts_utc = "2026-01-26T00:00:00+00:00"
            media.put_stream("media/2", BytesIO(b"stream-data"), ts_utc=ts_utc)
            safe_run = _encode_record_id("run1")
            safe_record = _encode_record_id("media/2")
            path = (
                Path(tmp)
                / "media"
                / safe_run
                / "evidence"
                / "2026"
                / "01"
                / "26"
                / f"{safe_record}.stream"
            )
            self.assertTrue(path.exists())
            payload = path.read_bytes()
            self.assertTrue(payload.startswith(STREAM_MAGIC))
            self.assertNotIn(b"stream-data", payload)
            self.assertEqual(media.get("media/2"), b"stream-data")


if __name__ == "__main__":
    unittest.main()
