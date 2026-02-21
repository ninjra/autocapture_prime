import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing
from plugins.builtin.storage_encrypted.plugin import DerivedKeyProvider, EncryptedJSONStore
from plugins.builtin.storage_sqlcipher.plugin import SQLCipherStore, migrate_metadata_json_to_sqlcipher


class SqlCipherMigrationTests(unittest.TestCase):
    def test_migrate_json_to_sqlcipher(self) -> None:
        try:
            import sqlcipher3  # noqa: F401
        except Exception:
            self.skipTest("sqlcipher3 not available")
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            keyring_path = data_dir / "keyring.json"
            root_key_path = data_dir / "root.key"
            keyring = KeyRing.load(str(keyring_path), legacy_root_path=str(root_key_path))
            provider = DerivedKeyProvider(keyring, "metadata")
            json_dir = data_dir / "metadata"
            json_store = EncryptedJSONStore(str(json_dir), provider, "run1")
            payload = {
                "record_type": "evidence.capture.segment",
                "run_id": "run1",
                "segment_id": "seg0",
                "ts_start_utc": "2024-01-01T00:00:00+00:00",
                "ts_end_utc": "2024-01-01T00:00:10+00:00",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "width": 1,
                "height": 1,
                "container": {"type": "zip"},
                "content_hash": "hash",
                "payload_hash": "payloadhash",
            }
            json_store.put_new("run1/segment/0", payload)

            config = {
                "runtime": {"run_id": "run1"},
                "storage": {
                    "data_dir": str(data_dir),
                    "metadata_path": str(data_dir / "metadata.db"),
                    "crypto": {
                        "keyring_path": str(keyring_path),
                        "root_key_path": str(root_key_path),
                    },
                },
            }
            result = migrate_metadata_json_to_sqlcipher(
                config,
                src_dir=str(json_dir),
                dst_path=str(data_dir / "metadata.db"),
                dry_run=False,
            )
            self.assertEqual(result.records_total, 1)
            self.assertEqual(result.records_copied, 1)
            _meta_id, meta_key = provider.active()
            sql_store = SQLCipherStore(str(data_dir / "metadata.db"), meta_key, "run1", "none")
            loaded = sql_store.get("run1/segment/0")
            self.assertEqual(payload, loaded)


if __name__ == "__main__":
    unittest.main()
