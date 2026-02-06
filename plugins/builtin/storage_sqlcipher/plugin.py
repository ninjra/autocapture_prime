"""SQLCipher-backed metadata store with AES-GCM media store."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

from dataclasses import dataclass

from autocapture_nx.kernel.crypto import EncryptedBlob, decrypt_bytes, encrypt_bytes
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from autocapture_nx.state_layer.store_sqlite import StateTapeStore
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from plugins.builtin.storage_encrypted.plugin import (
    DerivedKeyProvider,
    EncryptedBlobStore,
    EncryptedJSONStore,
    EntityMapStore,  # noqa: F401
    _atomic_write_bytes,
    _encode_record_id,
    _fsync_dir,
    _fsync_file,
    _iter_files,
    _legacy_safe_id,
    _parse_ts,
    _shard_dir,
    _FsyncPolicy,
    _extract_ts,
    BLOB_EXT,
    STREAM_EXT,
)


def _sqlcipher_available() -> tuple[bool, str | None]:
    try:
        import sqlcipher3  # noqa: F401
    except Exception as exc:
        return False, str(exc)
    return True, None


def sqlcipher_available() -> bool:
    ok, _reason = _sqlcipher_available()
    return ok


class _LazyStores:
    def __init__(self, builder):
        self._builder = builder
        self._lock = threading.Lock()
        self._ready = False
        self.metadata = None
        self.media = None
        self.entity_map = None
        self.state_tape = None

    def ensure(self) -> "_LazyStores":
        if self._ready:
            return self
        with self._lock:
            if not self._ready:
                self.metadata, self.media, self.entity_map, self.state_tape = self._builder()
                self._ready = True
        return self


class _LazyProxy:
    def __init__(self, stores: _LazyStores, attr: str) -> None:
        self._stores = stores
        self._attr = attr

    def _target(self):
        return getattr(self._stores.ensure(), self._attr)

    def __getattr__(self, name: str):
        return getattr(self._target(), name)

    def __dir__(self):
        try:
            return dir(self._target())
        except Exception:
            return super().__dir__()


@dataclass(frozen=True)
class MetadataMigrationResult:
    src_dir: str
    dst_path: str
    records_total: int
    records_copied: int
    records_skipped: int
    dry_run: bool


def migrate_metadata_json_to_sqlcipher(
    config: dict[str, Any],
    *,
    src_dir: str | None = None,
    dst_path: str | None = None,
    dry_run: bool = False,
) -> MetadataMigrationResult:
    storage_cfg = config.get("storage", {})
    data_dir = storage_cfg.get("data_dir", "data")
    src_dir = src_dir or storage_cfg.get("metadata_dir") or os.path.join(data_dir, "metadata")
    dst_path = dst_path or storage_cfg.get("metadata_path") or os.path.join(
        data_dir, "metadata", "metadata.db"
    )
    ok, reason = _sqlcipher_available()
    if not ok:
        raise RuntimeError(f"SQLCipher unavailable ({reason})")
    crypto_cfg = storage_cfg.get("crypto", {})
    keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
    root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
    encryption_required = bool(storage_cfg.get("encryption_required", False))
    require_protection = bool(encryption_required and os.name == "nt")
    backend = crypto_cfg.get("keyring_backend", "auto")
    credential_name = crypto_cfg.get("keyring_credential_name", "autocapture.keyring")
    keyring = KeyRing.load(
        keyring_path,
        legacy_root_path=root_key_path,
        require_protection=require_protection,
        backend=backend,
        credential_name=credential_name,
    )
    run_id = str(config.get("runtime", {}).get("run_id", "run"))
    fsync_policy = _FsyncPolicy.normalize(storage_cfg.get("fsync_policy"))
    meta_provider = DerivedKeyProvider(keyring, "metadata")
    _meta_id, meta_key = meta_provider.active()
    json_store = EncryptedJSONStore(
        src_dir,
        meta_provider,
        run_id,
        require_decrypt=encryption_required,
        fsync_policy=fsync_policy,
    )
    sql_store = SQLCipherStore(dst_path, meta_key, run_id, fsync_policy)
    total = 0
    copied = 0
    skipped = 0
    for record_id in json_store.keys():
        payload = json_store.get(record_id, None)
        if payload is None:
            continue
        total += 1
        if dry_run:
            continue
        try:
            sql_store.put_new(record_id, payload)
            copied += 1
        except FileExistsError:
            skipped += 1
    return MetadataMigrationResult(
        src_dir=str(src_dir),
        dst_path=str(dst_path),
        records_total=total,
        records_copied=copied,
        records_skipped=skipped,
        dry_run=dry_run,
    )


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
        conn = sqlcipher3.connect(self._db_path, check_same_thread=False)
        # sqlcipher3 does not support parameter binding for PRAGMA key.
        conn.execute(f"PRAGMA key = \"x'{self._key.hex()}'\"")
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
            "CREATE TABLE IF NOT EXISTS entity_map (token TEXT PRIMARY KEY, value TEXT, kind TEXT, key_id TEXT, key_version INTEGER, first_seen_ts TEXT)"
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
        cur = self._conn.execute("PRAGMA table_info(entity_map)")
        existing = {row[1] for row in cur.fetchall()}
        for column, col_type in (
            ("key_id", "TEXT"),
            ("key_version", "INTEGER"),
            ("first_seen_ts", "TEXT"),
        ):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE entity_map ADD COLUMN {column} {col_type}")

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

    def count(self) -> int:
        self._ensure()
        cur = self._conn.execute("SELECT COUNT(*) FROM metadata")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def query_time_window(
        self,
        start_ts: str | None,
        end_ts: str | None,
        limit: int | None = None,
    ) -> list[str]:
        self._ensure()
        clauses = []
        params: list[Any] = []
        if start_ts:
            clauses.append("ts_utc >= ?")
            params.append(start_ts)
        if end_ts:
            clauses.append("ts_utc <= ?")
            params.append(end_ts)
        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)
        sql = f"SELECT id FROM metadata {where} ORDER BY ts_utc, id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, tuple(params))
        return [row[0] for row in cur.fetchall()]

    def latest(self, record_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        import json

        self._ensure()
        params: list[Any] = []
        sql = "SELECT id, payload FROM metadata"
        if record_type:
            sql += " WHERE record_type = ?"
            params.append(str(record_type))
        sql += " ORDER BY ts_utc DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, tuple(params))
        rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            record_id = row[0]
            raw = row[1]
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"payload": raw}
            out.append({"record_id": record_id, "record": payload})
        return out

    def delete(self, record_id: str) -> bool:
        self._ensure()
        before = self._conn.total_changes
        self._conn.execute("DELETE FROM metadata WHERE id = ?", (record_id,))
        self._conn.commit()
        return self._conn.total_changes > before

    def entity_put(
        self,
        token: str,
        value: str,
        kind: str,
        *,
        key_id: str | None = None,
        key_version: int | None = None,
        first_seen_ts: str | None = None,
    ) -> None:
        self._ensure()
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_map (token, value, kind, key_id, key_version, first_seen_ts) VALUES (?, ?, ?, ?, ?, ?)",
            (token, value, kind, key_id, key_version, first_seen_ts),
        )
        self._conn.commit()

    def entity_get(self, token: str) -> dict[str, Any] | None:
        self._ensure()
        cur = self._conn.execute(
            "SELECT value, kind, key_id, key_version, first_seen_ts FROM entity_map WHERE token = ?",
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "value": row[0],
            "kind": row[1],
            "key_id": row[2],
            "key_version": row[3],
            "first_seen_ts": row[4],
        }

    def entity_items(self) -> dict[str, dict[str, Any]]:
        self._ensure()
        cur = self._conn.execute("SELECT token, value, kind, key_id, key_version, first_seen_ts FROM entity_map")
        return {
            row[0]: {
                "value": row[1],
                "kind": row[2],
                "key_id": row[3],
                "key_version": row[4],
                "first_seen_ts": row[5],
            }
            for row in cur.fetchall()
        }

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


class PlainSQLiteStore:
    def __init__(self, db_path: str, run_id: str, fsync_policy: str) -> None:
        self._db_path = db_path
        self._run_id = run_id
        self._fsync_policy = str(fsync_policy or "").strip().lower() or "none"
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _ensure(self) -> None:
        if self._conn is None:
            self._conn = self._connect()
            self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        self._apply_fsync_policy(conn)
        return conn

    def _apply_fsync_policy(self, conn: sqlite3.Connection) -> None:
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
            "CREATE TABLE IF NOT EXISTS entity_map (token TEXT PRIMARY KEY, value TEXT, kind TEXT, key_id TEXT, key_version INTEGER, first_seen_ts TEXT)"
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
        cur = self._conn.execute("PRAGMA table_info(entity_map)")
        existing = {row[1] for row in cur.fetchall()}
        for column, col_type in (
            ("key_id", "TEXT"),
            ("key_version", "INTEGER"),
            ("first_seen_ts", "TEXT"),
        ):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE entity_map ADD COLUMN {column} {col_type}")

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

    def count(self) -> int:
        self._ensure()
        cur = self._conn.execute("SELECT COUNT(*) FROM metadata")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def query_time_window(
        self,
        start_ts: str | None,
        end_ts: str | None,
        limit: int | None = None,
    ) -> list[str]:
        self._ensure()
        clauses = []
        params: list[Any] = []
        if start_ts:
            clauses.append("ts_utc >= ?")
            params.append(start_ts)
        if end_ts:
            clauses.append("ts_utc <= ?")
            params.append(end_ts)
        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)
        sql = f"SELECT id FROM metadata {where} ORDER BY ts_utc, id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, tuple(params))
        return [row[0] for row in cur.fetchall()]

    def latest(self, record_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        import json

        self._ensure()
        params: list[Any] = []
        sql = "SELECT id, payload FROM metadata"
        if record_type:
            sql += " WHERE record_type = ?"
            params.append(str(record_type))
        sql += " ORDER BY ts_utc DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, tuple(params))
        rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            record_id = row[0]
            raw = row[1]
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"payload": raw}
            out.append({"record_id": record_id, "record": payload})
        return out

    def delete(self, record_id: str) -> bool:
        self._ensure()
        before = self._conn.total_changes
        self._conn.execute("DELETE FROM metadata WHERE id = ?", (record_id,))
        self._conn.commit()
        return self._conn.total_changes > before

    def entity_put(
        self,
        token: str,
        value: str,
        kind: str,
        *,
        key_id: str | None = None,
        key_version: int | None = None,
        first_seen_ts: str | None = None,
    ) -> None:
        self._ensure()
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_map (token, value, kind, key_id, key_version, first_seen_ts) VALUES (?, ?, ?, ?, ?, ?)",
            (token, value, kind, key_id, key_version, first_seen_ts),
        )
        self._conn.commit()

    def entity_get(self, token: str) -> dict[str, Any] | None:
        self._ensure()
        cur = self._conn.execute(
            "SELECT value, kind, key_id, key_version, first_seen_ts FROM entity_map WHERE token = ?",
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "value": row[0],
            "kind": row[1],
            "key_id": row[2],
            "key_version": row[3],
            "first_seen_ts": row[4],
        }

    def entity_items(self) -> dict[str, dict[str, Any]]:
        self._ensure()
        cur = self._conn.execute("SELECT token, value, kind, key_id, key_version, first_seen_ts FROM entity_map")
        return {
            row[0]: {
                "value": row[1],
                "kind": row[2],
                "key_id": row[3],
                "key_version": row[4],
                "first_seen_ts": row[5],
            }
            for row in cur.fetchall()
        }

    def rotate(self, _new_key: bytes | None = None) -> None:
        return None

    def vacuum(self) -> None:
        self._ensure()
        self._conn.execute("VACUUM")
        self._conn.commit()


class PlainBlobStore:
    def __init__(self, root_dir: str, run_id: str, fsync_policy: str) -> None:
        self._root = root_dir
        self._run_id = run_id or "run"
        self._fsync_policy = fsync_policy
        self._index: dict[str, str] = {}
        self._count_cache: int | None = None
        os.makedirs(self._root, exist_ok=True)

    def _path_for_write(self, record_id: str, ts_utc: str | None, *, stream: bool) -> str:
        shard_dir = _shard_dir(self._root, self._run_id, ts_utc, record_id=record_id)
        safe = _encode_record_id(record_id)
        ext = STREAM_EXT if stream else BLOB_EXT
        return os.path.join(shard_dir, f"{safe}{ext}")

    def _path_candidates(self, record_id: str) -> list[str]:
        paths: list[str] = []
        if record_id in self._index:
            cached = self._index[record_id]
            if os.path.exists(cached):
                return [cached]
            self._index.pop(record_id, None)
        encoded = _encode_record_id(record_id)
        run_dir = os.path.join(self._root, _encode_record_id(self._run_id))
        if os.path.isdir(run_dir):
            for current, _dirs, files in os.walk(run_dir):
                for ext in (BLOB_EXT, STREAM_EXT):
                    name = f"{encoded}{ext}"
                    if name in files:
                        path = os.path.join(current, name)
                        self._index[record_id] = path
                        return [path]
        if os.path.isdir(self._root):
            for current, _dirs, files in os.walk(self._root):
                for ext in (BLOB_EXT, STREAM_EXT):
                    name = f"{encoded}{ext}"
                    if name in files:
                        path = os.path.join(current, name)
                        self._index[record_id] = path
                        return [path]
        paths.append(os.path.join(self._root, f"{encoded}{BLOB_EXT}"))
        paths.append(os.path.join(self._root, f"{encoded}{STREAM_EXT}"))
        legacy = _legacy_safe_id(record_id)
        paths.append(os.path.join(self._root, f"{legacy}.bin"))
        return paths

    def _remove_existing(self, record_id: str) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def put(self, record_id: str, data: bytes, *, ts_utc: str | None = None) -> None:
        self.put_replace(record_id, data, ts_utc=ts_utc)

    def put_replace(self, record_id: str, data: bytes, *, ts_utc: str | None = None) -> None:
        path = self._path_for_write(record_id, ts_utc, stream=False)
        existed = any(os.path.exists(path) for path in self._path_candidates(record_id))
        self._remove_existing(record_id)
        _atomic_write_bytes(path, data, fsync_policy=self._fsync_policy)
        self._index[record_id] = path
        if self._count_cache is not None and not existed:
            self._count_cache += 1

    def put_new(self, record_id: str, data: bytes, *, ts_utc: str | None = None) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                raise FileExistsError(f"Blob record already exists: {record_id}")
        self.put_replace(record_id, data, ts_utc=ts_utc)

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024, *, ts_utc: str | None = None) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                raise FileExistsError(f"Blob record already exists: {record_id}")
        self.put_stream_replace(record_id, stream, chunk_size=chunk_size, ts_utc=ts_utc)

    def put_stream_replace(
        self,
        record_id: str,
        stream,
        chunk_size: int = 1024 * 1024,
        *,
        ts_utc: str | None = None,
    ) -> None:
        path = self._path_for_write(record_id, ts_utc, stream=True)
        existed = any(os.path.exists(path) for path in self._path_candidates(record_id))
        self._remove_existing(record_id)
        tmp_path = f"{path}.tmp"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "wb") as handle:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
            _fsync_file(handle, self._fsync_policy)
        os.replace(tmp_path, path)
        _fsync_dir(path, self._fsync_policy)
        self._index[record_id] = path
        if self._count_cache is not None and not existed:
            self._count_cache += 1

    def put_path(self, record_id: str, path: str, *, ts_utc: str | None = None) -> None:
        with open(path, "rb") as handle:
            self.put_stream_replace(record_id, handle, ts_utc=ts_utc)

    def get(self, record_id: str, default: bytes | None = None) -> bytes | None:
        for path in self._path_candidates(record_id):
            if not os.path.exists(path):
                continue
            try:
                with open(path, "rb") as handle:
                    return handle.read()
            except OSError:
                continue
        return default

    def exists(self, record_id: str) -> bool:
        return any(os.path.exists(path) for path in self._path_candidates(record_id))

    def count(self) -> int:
        if self._count_cache is None:
            self._count_cache = len(list(_iter_files(self._root, [BLOB_EXT, STREAM_EXT, ".bin"])))
        return self._count_cache


class EncryptedSQLiteStore:
    def __init__(
        self,
        db_path: str,
        meta_provider: DerivedKeyProvider,
        entity_provider: DerivedKeyProvider,
        run_id: str,
        fsync_policy: str,
        *,
        require_decrypt: bool = False,
    ) -> None:
        self._db_path = db_path
        self._meta_provider = meta_provider
        self._entity_provider = entity_provider
        self._run_id = run_id
        self._require_decrypt = require_decrypt
        self._fsync_policy = str(fsync_policy or "").strip().lower() or "none"
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _ensure(self) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._apply_fsync_policy(self._conn)
            self._init_schema()

    def _apply_fsync_policy(self, conn: sqlite3.Connection) -> None:
        policy = self._fsync_policy
        if policy == "critical":
            conn.execute("PRAGMA synchronous = FULL")
        elif policy == "bulk":
            conn.execute("PRAGMA synchronous = NORMAL")
        elif policy == "none":
            conn.execute("PRAGMA synchronous = OFF")

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, nonce_b64 TEXT, ciphertext_b64 TEXT, key_id TEXT)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entity_map (token TEXT PRIMARY KEY, nonce_b64 TEXT, ciphertext_b64 TEXT, key_id TEXT)"
        )
        self._conn.commit()

    def _encrypt(self, provider: DerivedKeyProvider, payload: Any) -> tuple[str, str, str]:
        key_id, key = provider.active()
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        blob = encrypt_bytes(key, data, key_id=key_id)
        return blob.nonce_b64, blob.ciphertext_b64, key_id

    def _decrypt(
        self,
        provider: DerivedKeyProvider,
        nonce_b64: str,
        ciphertext_b64: str,
        key_id: str | None,
        *,
        default: Any = None,
    ) -> Any:
        blob = EncryptedBlob(nonce_b64=nonce_b64, ciphertext_b64=ciphertext_b64, key_id=key_id)
        for key in provider.candidates(key_id):
            try:
                payload = decrypt_bytes(key, blob)
                return json.loads(payload.decode("utf-8"))
            except Exception:
                continue
        if self._require_decrypt:
            raise RuntimeError("Decrypt failed for metadata record")
        return default

    def put(self, record_id: str, value: Any) -> None:
        self.put_replace(record_id, value)

    def put_replace(self, record_id: str, value: Any) -> None:
        self._ensure()
        nonce_b64, ciphertext_b64, key_id = self._encrypt(self._meta_provider, value)
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (id, nonce_b64, ciphertext_b64, key_id) VALUES (?, ?, ?, ?)",
            (record_id, nonce_b64, ciphertext_b64, key_id),
        )
        self._conn.commit()

    def put_new(self, record_id: str, value: Any) -> None:
        self._ensure()
        nonce_b64, ciphertext_b64, key_id = self._encrypt(self._meta_provider, value)
        try:
            self._conn.execute(
                "INSERT INTO metadata (id, nonce_b64, ciphertext_b64, key_id) VALUES (?, ?, ?, ?)",
                (record_id, nonce_b64, ciphertext_b64, key_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise FileExistsError(f"Metadata record already exists: {record_id}") from exc

    def get(self, record_id: str, default: Any = None) -> Any:
        self._ensure()
        cur = self._conn.execute(
            "SELECT nonce_b64, ciphertext_b64, key_id FROM metadata WHERE id = ?",
            (record_id,),
        )
        row = cur.fetchone()
        if not row:
            return default
        return self._decrypt(self._meta_provider, row[0], row[1], row[2], default=default)

    def keys(self) -> list[str]:
        self._ensure()
        cur = self._conn.execute("SELECT id FROM metadata ORDER BY id")
        return [row[0] for row in cur.fetchall()]

    def count(self) -> int:
        self._ensure()
        cur = self._conn.execute("SELECT COUNT(*) FROM metadata")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def query_time_window(
        self,
        start_ts: str | None,
        end_ts: str | None,
        limit: int | None = None,
    ) -> list[str]:
        self._ensure()
        start_key = _parse_ts(start_ts).timestamp() if start_ts else None
        end_key = _parse_ts(end_ts).timestamp() if end_ts else None
        matched: list[tuple[float, str]] = []
        for record_id in self.keys():
            record = self.get(record_id)
            if not isinstance(record, dict):
                continue
            ts_val = _extract_ts(record)
            if not ts_val:
                continue
            ts_key = _parse_ts(ts_val).timestamp()
            if start_key is not None and ts_key < start_key:
                continue
            if end_key is not None and ts_key > end_key:
                continue
            matched.append((ts_key, record_id))
        matched.sort(key=lambda item: (item[0], item[1]))
        if limit is not None:
            matched = matched[: int(limit)]
        return [record_id for _ts, record_id in matched]

    def latest(self, record_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        import heapq

        limit_val = int(limit) if limit is not None else 25
        limit_val = max(1, limit_val)
        heap: list[tuple[float, str, dict[str, Any]]] = []
        for record_id in self.keys():
            record = self.get(record_id)
            if not isinstance(record, dict):
                continue
            if record_type and record.get("record_type") != record_type:
                continue
            ts_val = _extract_ts(record)
            if not ts_val:
                continue
            ts_key = _parse_ts(ts_val).timestamp()
            entry = (ts_key, record_id, record)
            if len(heap) < limit_val:
                heapq.heappush(heap, entry)
            else:
                if entry[0] > heap[0][0]:
                    heapq.heapreplace(heap, entry)
        heap.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [{"record_id": record_id, "record": record} for _ts, record_id, record in heap]

    def delete(self, record_id: str) -> bool:
        self._ensure()
        before = self._conn.total_changes
        self._conn.execute("DELETE FROM metadata WHERE id = ?", (record_id,))
        self._conn.commit()
        return self._conn.total_changes > before

    def entity_put(
        self,
        token: str,
        value: str,
        kind: str,
        *,
        key_id: str | None = None,
        key_version: int | None = None,
        first_seen_ts: str | None = None,
    ) -> None:
        self._ensure()
        payload = {
            "value": value,
            "kind": kind,
            "key_id": key_id,
            "key_version": key_version,
            "first_seen_ts": first_seen_ts,
        }
        nonce_b64, ciphertext_b64, enc_key_id = self._encrypt(self._entity_provider, payload)
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_map (token, nonce_b64, ciphertext_b64, key_id) VALUES (?, ?, ?, ?)",
            (token, nonce_b64, ciphertext_b64, enc_key_id),
        )
        self._conn.commit()

    def entity_get(self, token: str) -> dict[str, Any] | None:
        self._ensure()
        cur = self._conn.execute(
            "SELECT nonce_b64, ciphertext_b64, key_id FROM entity_map WHERE token = ?",
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._decrypt(self._entity_provider, row[0], row[1], row[2], default=None)

    def entity_items(self) -> dict[str, dict[str, Any]]:
        self._ensure()
        cur = self._conn.execute("SELECT token, nonce_b64, ciphertext_b64, key_id FROM entity_map")
        out: dict[str, dict[str, Any]] = {}
        for row in cur.fetchall():
            token = row[0]
            payload = self._decrypt(self._entity_provider, row[1], row[2], row[3], default=None)
            if isinstance(payload, dict):
                out[token] = payload
        return out


class EntityMapAdapter:
    def __init__(self, store: SQLCipherStore) -> None:
        self._store = store

    def put(
        self,
        token: str,
        value: str,
        kind: str,
        *,
        key_id: str | None = None,
        key_version: int | None = None,
        first_seen_ts: str | None = None,
    ) -> None:
        self._store.entity_put(
            token,
            value,
            kind,
            key_id=key_id,
            key_version=key_version,
            first_seen_ts=first_seen_ts,
        )

    def get(self, token: str) -> dict[str, Any] | None:
        return self._store.entity_get(token)

    def items(self) -> dict[str, dict[str, Any]]:
        return self._store.entity_items()


class SQLCipherStoragePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage_cfg = context.config.get("storage", {})
        crypto_cfg = storage_cfg.get("crypto", {})
        keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
        root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
        encryption_required = storage_cfg.get("encryption_required", False)
        encryption_enabled = storage_cfg.get("encryption_enabled", True)
        require_protection = bool(encryption_required and os.name == "nt")
        backend = crypto_cfg.get("keyring_backend", "auto")
        credential_name = crypto_cfg.get("keyring_credential_name", "autocapture.keyring")
        keyring = KeyRing.load(
            keyring_path,
            legacy_root_path=root_key_path,
            require_protection=require_protection,
            backend=backend,
            credential_name=credential_name,
        )
        self._keyring = keyring
        self._meta_provider = DerivedKeyProvider(keyring, "metadata")
        self._media_provider = DerivedKeyProvider(keyring, "media")
        self._entity_provider = DerivedKeyProvider(keyring, "entity_tokens")
        self._state_provider = DerivedKeyProvider(keyring, "state_tape")
        data_dir = storage_cfg.get("data_dir", "data")
        run_id = str(context.config.get("runtime", {}).get("run_id", "run"))
        fsync_policy = _FsyncPolicy.normalize(storage_cfg.get("fsync_policy"))
        require_decrypt = bool(encryption_required)
        legacy_meta_path = os.path.join(data_dir, "metadata", "metadata.db")
        metadata_path = storage_cfg.get("metadata_path")
        if metadata_path:
            if not os.path.exists(metadata_path) and os.path.exists(legacy_meta_path):
                metadata_path = legacy_meta_path
        else:
            metadata_path = legacy_meta_path
        self._metadata_dir = storage_cfg.get("metadata_dir") or os.path.join(data_dir, "metadata")
        self._metadata_path = metadata_path
        self._data_dir = data_dir
        self._media_dir = storage_cfg.get("media_dir") or os.path.join(data_dir, "media")
        self._state_tape_path = storage_cfg.get("state_tape_path") or os.path.join(data_dir, "state", "state_tape.db")
        self._run_id = run_id
        self._fsync_policy = fsync_policy
        self._require_decrypt = require_decrypt
        self._entity_persist = storage_cfg.get("entity_map", {}).get("persist", True)
        self._metadata_require_db = bool(storage_cfg.get("metadata_require_db", False))
        self._encryption_enabled = bool(encryption_enabled)
        self._lazy = _LazyStores(self._build_stores)
        self._metadata = _LazyProxy(self._lazy, "metadata")
        self._entity_map = _LazyProxy(self._lazy, "entity_map")
        self._media = _LazyProxy(self._lazy, "media")
        self._state_tape = _LazyProxy(self._lazy, "state_tape")

    def _build_stores(self):
        state_tape = None
        if self._encryption_enabled:
            available, reason = _sqlcipher_available()
            if available:
                _meta_id, meta_key = self._meta_provider.active()
                store = SQLCipherStore(self._metadata_path, meta_key, self._run_id, self._fsync_policy)
                metadata = ImmutableMetadataStore(store)
                entity_map = EntityMapAdapter(store)
            else:
                if self._metadata_require_db:
                    self.context.logger(
                        f"SQLCipher unavailable ({reason}); using encrypted SQLite fallback"
                    )
                metadata_store = EncryptedSQLiteStore(
                    self._metadata_path,
                    self._meta_provider,
                    self._entity_provider,
                    self._run_id,
                    self._fsync_policy,
                    require_decrypt=self._require_decrypt,
                )
                metadata = ImmutableMetadataStore(metadata_store)
                entity_map = EntityMapAdapter(metadata_store)
            media = EncryptedBlobStore(
                self._media_dir,
                self._media_provider,
                self._run_id,
                require_decrypt=self._require_decrypt,
                fsync_policy=self._fsync_policy,
            )
            state_key = None
            if available:
                _state_id, state_key = self._state_provider.active()
            elif self._require_decrypt:
                self.context.logger(
                    f"SQLCipher unavailable ({reason}); using unencrypted state tape store"
                )
            state_tape = StateTapeStore(self._state_tape_path, key=state_key, fsync_policy=self._fsync_policy)
            return metadata, media, entity_map, state_tape

        store = PlainSQLiteStore(self._metadata_path, self._run_id, self._fsync_policy)
        metadata = ImmutableMetadataStore(store)
        entity_map = EntityMapAdapter(store)
        media = PlainBlobStore(self._media_dir, self._run_id, self._fsync_policy)
        state_tape = StateTapeStore(self._state_tape_path, key=None, fsync_policy=self._fsync_policy)
        return metadata, media, entity_map, state_tape

    def capabilities(self) -> dict[str, Any]:
        return {
            "storage.metadata": self._metadata,
            "storage.media": self._media,
            "storage.entity_map": self._entity_map,
            "storage.state_tape": self._state_tape,
            "storage.keyring": self._keyring,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> SQLCipherStoragePlugin:
    return SQLCipherStoragePlugin(plugin_id, context)
