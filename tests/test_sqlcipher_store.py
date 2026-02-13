import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_sqlcipher.plugin import PlainSQLiteStore, SQLCipherStoragePlugin


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

    def test_plain_sqlite_readonly_mode_allows_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "metadata.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT)"
            )
            conn.execute(
                "CREATE TABLE entity_map (token TEXT PRIMARY KEY, value TEXT, kind TEXT, key_id TEXT, key_version INTEGER, first_seen_ts TEXT)"
            )
            conn.execute(
                "INSERT INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
                ("k_read", "{\"v\":1}", "derived.test", "2026-02-11T00:00:00Z", "run1"),
            )
            conn.commit()
            conn.close()

            store = PlainSQLiteStore(db_path, "run1", "none")
            with patch.object(
                PlainSQLiteStore,
                "_init_schema",
                side_effect=sqlite3.OperationalError("attempt to write a readonly database"),
            ):
                keys = store.keys()
                self.assertIn("k_read", keys)
                store.put_new("k_skip", {"v": 2})
                self.assertIsNone(store.get("k_skip"))


if __name__ == "__main__":
    unittest.main()
