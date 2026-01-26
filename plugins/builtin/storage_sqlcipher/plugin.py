"""SQLCipher-backed metadata store with AES-GCM media store."""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from plugins.builtin.storage_encrypted.plugin import (
    DerivedKeyProvider,
    EncryptedBlobStore,
    EncryptedJSONStore,
    EntityMapStore,
    _FsyncPolicy,
)


def _sqlcipher_available() -> tuple[bool, str | None]:
    try:
        import sqlcipher3  # noqa: F401
    except Exception as exc:
        return False, str(exc)
    return True, None


class SQLCipherStore:
    def __init__(self, db_path: str, key: bytes, run_id: str, fsync_policy: str) -> None:
        self._db_path = db_path
        self._key = key
        self._run_id = run_id
        self._fsync_policy = str(fsync_policy or "").strip().lower() or "none"
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = None

    def _ensure(self) -> None:
        if self._conn is None:
            self._conn = self._connect()
            self._init_schema()

    def _connect(self):
        try:
            import sqlcipher3
        except Exception as exc:
            raise RuntimeError(f"Missing SQLCipher dependency: {exc}")
        conn = sqlcipher3.connect(self._db_path)
        conn.execute("PRAGMA key = ?", (self._key.hex(),))
        self._apply_fsync_policy(conn)
        return conn

    def _apply_fsync_policy(self, conn) -> None:
        policy = self._fsync_policy
        if policy == "critical":
            conn.execute("PRAGMA synchronous = FULL")
        elif policy == "bulk":
            conn.execute("PRAGMA synchronous = NORMAL")
        elif policy == "none":
            conn.execute("PRAGMA synchronous = OFF")

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entity_map (token TEXT PRIMARY KEY, value TEXT, kind TEXT)"
        )
        self._ensure_columns()
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_record_type ON metadata(record_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_ts_utc ON metadata(ts_utc)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_run_id ON metadata(run_id)"
        )
        self._conn.commit()

    def _ensure_columns(self) -> None:
        cur = self._conn.execute("PRAGMA table_info(metadata)")
        existing = {row[1] for row in cur.fetchall()}
        for column, col_type in (
            ("record_type", "TEXT"),
            ("ts_utc", "TEXT"),
            ("run_id", "TEXT"),
        ):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE metadata ADD COLUMN {column} {col_type}")

    def put(self, record_id: str, value: Any) -> None:
        self.put_replace(record_id, value)

    def put_replace(self, record_id: str, value: Any) -> None:
        import json

        self._ensure()
        record_type = None
        ts_utc = None
        run_id = self._run_id
        if isinstance(value, dict):
            record_type = value.get("record_type")
            ts_utc = value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc")
            run_id = value.get("run_id") or run_id
        payload = json.dumps(value, sort_keys=True)
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
            (record_id, payload, record_type, ts_utc, run_id),
        )
        self._conn.commit()

    def put_new(self, record_id: str, value: Any) -> None:
        import json

        self._ensure()
        record_type = None
        ts_utc = None
        run_id = self._run_id
        if isinstance(value, dict):
            record_type = value.get("record_type")
            ts_utc = value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc")
            run_id = value.get("run_id") or run_id
        payload = json.dumps(value, sort_keys=True)
        try:
            self._conn.execute(
                "INSERT INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
                (record_id, payload, record_type, ts_utc, run_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise FileExistsError(f"Metadata record already exists: {record_id}") from exc

    def get(self, record_id: str, default: Any = None) -> Any:
        import json

        self._ensure()
        cur = self._conn.execute("SELECT payload FROM metadata WHERE id = ?", (record_id,))
        row = cur.fetchone()
        if not row:
            return default
        return json.loads(row[0])

    def keys(self) -> list[str]:
        self._ensure()
        cur = self._conn.execute("SELECT id FROM metadata ORDER BY id")
        return [row[0] for row in cur.fetchall()]

    def delete(self, record_id: str) -> bool:
        self._ensure()
        before = self._conn.total_changes
        self._conn.execute("DELETE FROM metadata WHERE id = ?", (record_id,))
        self._conn.commit()
        return self._conn.total_changes > before

    def entity_put(self, token: str, value: str, kind: str) -> None:
        self._ensure()
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_map (token, value, kind) VALUES (?, ?, ?)",
            (token, value, kind),
        )
        self._conn.commit()

    def entity_get(self, token: str) -> dict[str, str] | None:
        self._ensure()
        cur = self._conn.execute("SELECT value, kind FROM entity_map WHERE token = ?", (token,))
        row = cur.fetchone()
        if not row:
            return None
        return {"value": row[0], "kind": row[1]}

    def entity_items(self) -> dict[str, dict[str, str]]:
        self._ensure()
        cur = self._conn.execute("SELECT token, value, kind FROM entity_map")
        return {row[0]: {"value": row[1], "kind": row[2]} for row in cur.fetchall()}

    def rotate(self, new_key: bytes | None = None) -> None:
        if new_key is None:
            return
        self._ensure()
        self._conn.execute("PRAGMA rekey = ?", (new_key.hex(),))
        self._conn.commit()
        self._key = new_key

    def vacuum(self) -> None:
        self._ensure()
        self._conn.execute("VACUUM")
        self._conn.commit()


class EntityMapAdapter:
    def __init__(self, store: SQLCipherStore) -> None:
        self._store = store

    def put(self, token: str, value: str, kind: str) -> None:
        self._store.entity_put(token, value, kind)

    def get(self, token: str) -> dict[str, str] | None:
        return self._store.entity_get(token)

    def items(self) -> dict[str, dict[str, str]]:
        return self._store.entity_items()


class SQLCipherStoragePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage_cfg = context.config.get("storage", {})
        crypto_cfg = storage_cfg.get("crypto", {})
        keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
        root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
        encryption_required = storage_cfg.get("encryption_required", False)
        require_protection = bool(encryption_required and os.name == "nt")
        keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=require_protection)
        meta_provider = DerivedKeyProvider(keyring, "metadata")
        media_provider = DerivedKeyProvider(keyring, "media")
        entity_provider = DerivedKeyProvider(keyring, "entity_tokens")
        data_dir = storage_cfg.get("data_dir", "data")
        run_id = str(context.config.get("runtime", {}).get("run_id", "run"))
        fsync_policy = _FsyncPolicy.normalize(storage_cfg.get("fsync_policy"))
        require_decrypt = bool(encryption_required)
        available, reason = _sqlcipher_available()
        if available:
            _meta_id, meta_key = meta_provider.active()
            store = SQLCipherStore(os.path.join(data_dir, "metadata", "metadata.db"), meta_key, run_id, fsync_policy)
            self._metadata = ImmutableMetadataStore(store)
            self._entity_map = EntityMapAdapter(store)
        else:
            context.logger(f"SQLCipher unavailable ({reason}); falling back to encrypted JSON store")
            self._metadata = ImmutableMetadataStore(
                EncryptedJSONStore(
                    os.path.join(data_dir, "metadata"),
                    meta_provider,
                    run_id,
                    require_decrypt=require_decrypt,
                    fsync_policy=fsync_policy,
                )
            )
            persist = storage_cfg.get("entity_map", {}).get("persist", True)
            self._entity_map = EntityMapStore(
                os.path.join(data_dir, "entity_map"),
                entity_provider,
                persist,
                require_decrypt=require_decrypt,
                fsync_policy=fsync_policy,
            )
        self._media = EncryptedBlobStore(
            os.path.join(data_dir, "media"),
            media_provider,
            run_id,
            require_decrypt=require_decrypt,
            fsync_policy=fsync_policy,
        )
        self._keyring = keyring

    def capabilities(self) -> dict[str, Any]:
        return {
            "storage.metadata": self._metadata,
            "storage.media": self._media,
            "storage.entity_map": self._entity_map,
            "storage.keyring": self._keyring,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> SQLCipherStoragePlugin:
    return SQLCipherStoragePlugin(plugin_id, context)
