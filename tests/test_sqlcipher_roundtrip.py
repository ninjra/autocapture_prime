import json
import tempfile
import unittest
from pathlib import Path

import os

from autocapture.storage.sqlcipher import open_metadata_store, sqlcipher_available
from autocapture.config.load import load_config
from autocapture.config.models import ConfigPaths


class SqlCipherRoundtripTests(unittest.TestCase):
    def test_roundtrip_and_encryption(self) -> None:
        ok, reason = sqlcipher_available()
        if not ok:
            raise unittest.SkipTest(
                f"sqlcipher unavailable on {os.name}: {reason or 'missing dependency'}; install sqlcipher3"
            )
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
                    "metadata_path": f"{tmp}/metadata.db",
                    "crypto": {
                        "keyring_path": f"{tmp}/keyring.json",
                        "root_key_path": f"{tmp}/root.key",
                    },
                }
            }
            paths.user_path.write_text(json.dumps(override), encoding="utf-8")
            config = load_config(paths, safe_mode=False)
            store = open_metadata_store(config)
            payload = {"text": "secret-value", "ts": "2026-01-01"}
            store.put("rec1", payload)
            loaded = store.get("rec1")
            self.assertEqual(payload, loaded)
            db_bytes = Path(override["storage"]["metadata_path"]).read_bytes()
            self.assertNotIn(b"secret-value", db_bytes)


if __name__ == "__main__":
    unittest.main()
