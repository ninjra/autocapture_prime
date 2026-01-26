import json
import tempfile
import unittest
from pathlib import Path

from autocapture.config.load import load_config
from autocapture.config.models import ConfigPaths
from autocapture.storage.blob_store import BlobStore
from autocapture.storage.database import EncryptedMetadataStore
from autocapture.storage.keys import load_keyring


class StorageAppendOnlyTests(unittest.TestCase):
    def _config_paths(self, tmp: str) -> ConfigPaths:
        return ConfigPaths(
            default_path=Path("config/default.json"),
            user_path=Path(tmp) / "user.json",
            schema_path=Path("contracts/config_schema.json"),
            backup_dir=Path(tmp) / "backup",
        )

    def test_blob_store_put_if_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blob_dir = Path(tmp) / "blobs"
            override = {
                "storage": {
                    "data_dir": tmp,
                    "blob_dir": str(blob_dir),
                    "crypto": {
                        "keyring_path": f"{tmp}/keyring.json",
                        "root_key_path": f"{tmp}/root.key",
                    },
                }
            }
            paths = self._config_paths(tmp)
            paths.user_path.write_text(json.dumps(override), encoding="utf-8")
            config = load_config(paths, safe_mode=False)
            store = BlobStore(blob_dir, load_keyring(config))

            payload = b"append-only-blob"
            blob_id = store.put(payload)
            blob_path = blob_dir / f"{blob_id}.blob"
            before = blob_path.read_bytes()

            blob_id_again = store.put(payload)
            after = blob_path.read_bytes()

            self.assertEqual(blob_id, blob_id_again)
            self.assertEqual(before, after)

    def test_metadata_store_put_if_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = Path(tmp) / "metadata.db"
            override = {
                "storage": {
                    "data_dir": tmp,
                    "metadata_path": str(meta_path),
                    "crypto": {
                        "keyring_path": f"{tmp}/keyring.json",
                        "root_key_path": f"{tmp}/root.key",
                    },
                }
            }
            paths = self._config_paths(tmp)
            paths.user_path.write_text(json.dumps(override), encoding="utf-8")
            config = load_config(paths, safe_mode=False)
            store = EncryptedMetadataStore(meta_path, load_keyring(config))

            payload = {"value": "first", "ts": "2026-01-01"}
            store.put("rec1", payload)
            store.put("rec1", payload)

            with self.assertRaises(ValueError):
                store.put("rec1", {"value": "second", "ts": "2026-01-01"})


if __name__ == "__main__":
    unittest.main()
