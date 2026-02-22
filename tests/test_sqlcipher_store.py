import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_sqlcipher.plugin import (
    EncryptedSQLiteStore,
    PlainSQLiteStore,
    SQLCipherStoragePlugin,
    _resolve_metadata_path,
)


class _TestProvider:
    def active(self):
        return "k1", b"x" * 32

    def candidates(self, key_id=None):  # noqa: ARG002
        return [b"x" * 32]


class SQLCipherStoreTests(unittest.TestCase):
    @staticmethod
    def _create_metadata_db(path: str) -> None:
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT)"
        )
        conn.commit()
        conn.close()

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

    def test_plain_sqlite_init_failure_resets_connection_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "metadata.db")
            store = PlainSQLiteStore(db_path, "run1", "none")
            original = PlainSQLiteStore._init_schema
            calls = {"n": 0}

            def flaky_init(inst):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise sqlite3.OperationalError("disk I/O error")
                return original(inst)

            with patch.object(PlainSQLiteStore, "_init_schema", new=flaky_init):
                with self.assertRaises(sqlite3.OperationalError):
                    store.count()
                self.assertIsNone(store._conn)
                self.assertEqual(store.count(), 0)

    def test_encrypted_sqlite_init_failure_resets_connection_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "metadata.db")
            store = EncryptedSQLiteStore(
                db_path,
                _TestProvider(),
                _TestProvider(),
                "run1",
                "none",
            )
            original = EncryptedSQLiteStore._init_schema
            calls = {"n": 0}

            def flaky_init(inst):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise sqlite3.OperationalError("disk I/O error")
                return original(inst)

            with patch.object(EncryptedSQLiteStore, "_init_schema", new=flaky_init):
                with self.assertRaises(sqlite3.OperationalError):
                    store.count()
                self.assertIsNone(store._conn)
                self.assertEqual(store.count(), 0)

    def test_encrypted_sqlite_fallback_migrates_legacy_metadata_schema(self):
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
                (
                    "legacy_record",
                    "{\"schema_version\":1,\"record_type\":\"derived.legacy\",\"run_id\":\"run0\",\"content_hash\":\"h0\",\"v\":0}",
                    "derived.legacy",
                    "2026-02-10T00:00:00Z",
                    "run0",
                ),
            )
            conn.execute(
                "INSERT INTO entity_map (token, value, kind, key_id, key_version, first_seen_ts) VALUES (?, ?, ?, ?, ?, ?)",
                ("legacy_token", "legacy@example.com", "email", "legacy", 1, "2026-02-10T00:00:00Z"),
            )
            conn.commit()
            conn.close()

            config = {
                "storage": {
                    "data_dir": tmp,
                    "metadata_path": db_path,
                    "encryption_enabled": True,
                    "encryption_required": False,
                    "sqlcipher": {"enabled": False},
                    "crypto": {
                        "root_key_path": os.path.join(tmp, "vault", "root.key"),
                        "keyring_path": os.path.join(tmp, "vault", "keyring.json"),
                    },
                },
                "runtime": {"run_id": "run1"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            plugin = SQLCipherStoragePlugin("sql", ctx)
            metadata = plugin.capabilities()["storage.metadata"]
            entity = plugin.capabilities()["storage.entity_map"]

            legacy = metadata.get("legacy_record")
            self.assertIsInstance(legacy, dict)
            self.assertEqual(legacy.get("v"), 0)

            metadata.put(
                "new_record",
                {
                    "schema_version": 1,
                    "record_type": "derived.test",
                    "run_id": "run1",
                    "content_hash": "h1",
                    "v": 1,
                },
            )
            roundtrip = metadata.get("new_record")
            self.assertIsInstance(roundtrip, dict)
            self.assertEqual(roundtrip.get("v"), 1)

            legacy_entity = entity.get("legacy_token")
            self.assertIsNotNone(legacy_entity)
            self.assertEqual((legacy_entity or {}).get("value"), "legacy@example.com")
            self.assertEqual((legacy_entity or {}).get("kind"), "email")

            entity.put("new_token", "new@example.com", "email")
            new_entity = entity.get("new_token")
            self.assertIsNotNone(new_entity)
            self.assertEqual((new_entity or {}).get("value"), "new@example.com")
            self.assertEqual((new_entity or {}).get("kind"), "email")

            conn = sqlite3.connect(db_path)
            metadata_cols = {row[1] for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
            entity_cols = {row[1] for row in conn.execute("PRAGMA table_info(entity_map)").fetchall()}
            row = conn.execute(
                "SELECT payload, nonce_b64, ciphertext_b64, key_id FROM metadata WHERE id = ?",
                ("new_record",),
            ).fetchone()
            conn.close()

            self.assertIn("nonce_b64", metadata_cols)
            self.assertIn("ciphertext_b64", metadata_cols)
            self.assertIn("key_id", metadata_cols)
            self.assertIn("nonce_b64", entity_cols)
            self.assertIn("ciphertext_b64", entity_cols)
            self.assertIn("key_id", entity_cols)
            self.assertIsNotNone(row)
            self.assertEqual((row or ("", "", "", ""))[0], "")
            self.assertTrue(bool((row or ("", "", "", ""))[1]))
            self.assertTrue(bool((row or ("", "", "", ""))[2]))

    def test_resolve_metadata_path_uses_primary_when_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = os.path.join(tmp, "metadata.db")
            fallback = os.path.join(tmp, "metadata.live.db")
            self._create_metadata_db(primary)
            self._create_metadata_db(fallback)
            out = _resolve_metadata_path(
                {"metadata_path": primary, "metadata_fallback_paths": [fallback]},
                data_dir=tmp,
                legacy_meta_path=primary,
            )
            self.assertEqual(out, primary)

    def test_resolve_metadata_path_uses_fallback_when_primary_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = os.path.join(tmp, "metadata.db")
            fallback = os.path.join(tmp, "metadata.live.db")
            self._create_metadata_db(primary)
            self._create_metadata_db(fallback)
            real_connect = sqlite3.connect

            def flaky_connect(target, *args, **kwargs):
                if os.path.abspath(str(target)) == os.path.abspath(primary):
                    raise sqlite3.OperationalError("disk I/O error")
                return real_connect(target, *args, **kwargs)

            with patch("plugins.builtin.storage_sqlcipher.plugin.sqlite3.connect", side_effect=flaky_connect):
                out = _resolve_metadata_path(
                    {"metadata_path": primary, "metadata_fallback_paths": [fallback]},
                    data_dir=tmp,
                    legacy_meta_path=primary,
                )
            self.assertEqual(out, fallback)

    def test_resolve_metadata_path_uses_existing_fallback_when_primary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = os.path.join(tmp, "metadata.db")
            fallback = os.path.join(tmp, "metadata.live.db")
            self._create_metadata_db(fallback)
            out = _resolve_metadata_path(
                {"metadata_path": primary, "metadata_fallback_paths": [fallback]},
                data_dir=tmp,
                legacy_meta_path=primary,
            )
            self.assertEqual(out, fallback)


if __name__ == "__main__":
    unittest.main()
