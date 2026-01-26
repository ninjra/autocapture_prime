"""SQLCipher-backed metadata store with AES-GCM media store."""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from plugins.builtin.storage_encrypted.plugin import DerivedKeyProvider, EncryptedBlobStore


class SQLCipherStore:
    def __init__(self, db_path: str, key: bytes) -> None:
        self._db_path = db_path
        self._key = key
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = None

    def _ensure(self):
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
        return conn

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, payload TEXT)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entity_map (token TEXT PRIMARY KEY, value TEXT, kind TEXT)"
        )
        self._conn.commit()

    def put(self, record_id: str, value: Any) -> None:
        import json

        self._ensure()
        payload = json.dumps(value, sort_keys=True)
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (id, payload) VALUES (?, ?)",
            (record_id, payload),
        )
        self._conn.commit()

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
        data_dir = storage_cfg.get("data_dir", "data")
        _meta_id, meta_key = meta_provider.active()
        self._metadata = ImmutableMetadataStore(SQLCipherStore(os.path.join(data_dir, "metadata", "metadata.db"), meta_key))
        self._media = EncryptedBlobStore(os.path.join(data_dir, "media"), media_provider, require_decrypt=bool(encryption_required))
        self._entity_map = EntityMapAdapter(self._metadata)
        self._keyring = keyring
        self._meta_provider = meta_provider

    def capabilities(self) -> dict[str, Any]:
        return {
            "storage.metadata": self._metadata,
            "storage.media": self._media,
            "storage.entity_map": self._entity_map,
            "storage.keyring": self._keyring,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> SQLCipherStoragePlugin:
    return SQLCipherStoragePlugin(plugin_id, context)
