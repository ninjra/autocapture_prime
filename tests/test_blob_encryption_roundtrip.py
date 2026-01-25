import json
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.blob_store import BlobStore
from autocapture.storage.keys import load_keyring
from autocapture.config.load import load_config
from autocapture.config.models import ConfigPaths


class BlobEncryptionRoundtripTests(unittest.TestCase):
    def test_blob_encryption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ConfigPaths(
                default_path=Path("config/default.json"),
                user_path=Path(tmp) / "user.json",
                schema_path=Path("contracts/config_schema.json"),
                backup_dir=Path(tmp) / "backup",
            )
            override = {
                "storage": {
                    "data_dir": tmp,
                    "blob_dir": f"{tmp}/blobs",
                    "crypto": {
                        "keyring_path": f"{tmp}/keyring.json",
                        "root_key_path": f"{tmp}/root.key",
                    },
                }
            }
            paths.user_path.write_text(json.dumps(override), encoding="utf-8")
            config = load_config(paths, safe_mode=False)
            store = BlobStore(Path(override["storage"]["blob_dir"]), load_keyring(config))
            data = b"secret-blob-data"
            blob_id = store.put(data)
            loaded = store.get(blob_id)
            self.assertEqual(data, loaded)
            blob_path = Path(override["storage"]["blob_dir"]) / f"{blob_id}.blob"
            self.assertNotIn(data, blob_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
