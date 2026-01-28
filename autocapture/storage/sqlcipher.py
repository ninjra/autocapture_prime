"""SQLCipher-backed metadata store with fallback encryption."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocapture.storage.database import EncryptedMetadataStore
from autocapture.storage.keys import load_keyring
from autocapture_nx.kernel.crypto import derive_key


def _sqlcipher_available() -> tuple[bool, str | None]:
    try:
        import sqlcipher3  # noqa: F401
    except Exception as exc:
        return False, str(exc)
    return True, None


def _apply_fsync_policy(conn, policy: str) -> None:
    policy = str(policy or "").strip().lower() or "none"
    if policy == "critical":
        conn.execute("PRAGMA synchronous = FULL")
    elif policy == "bulk":
        conn.execute("PRAGMA synchronous = NORMAL")
    elif policy == "none":
        conn.execute("PRAGMA synchronous = OFF")


def _extract_ts(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("ts_utc", "ts_start_utc", "ts_end_utc"):
            if value.get(key):
                return str(value.get(key))
    return None


class _SQLCipherStore:
    def __init__(self, path: str | Path, key: bytes, run_id: str, fsync_policy: str) -> None:
        self._path = Path(path)
        self._key = key
        self._run_id = run_id
        self._fsync_policy = fsync_policy
        self._conn = None
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        import sqlcipher3

        conn = sqlcipher3.connect(str(self._path))
        conn.execute("PRAGMA key = ?", (self._key.hex(),))
        _apply_fsync_policy(conn, self._fsync_policy)
        return conn

    def _ensure(self) -> None:
        if self._conn is None:
            self._conn = self._connect()
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT)"
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
        existing = self.get(record_id, default=None)
        if existing is not None:
            if existing == value:
                return
            raise ValueError(f"record already exists: {record_id}")
        self.put_new(record_id, value)

    def put_replace(self, record_id: str, value: Any) -> None:
        self._ensure()
        record_type = value.get("record_type") if isinstance(value, dict) else None
        ts_utc = _extract_ts(value)
        run_id = value.get("run_id") if isinstance(value, dict) else None
        if not run_id:
            run_id = self._run_id
        payload = json.dumps(value, sort_keys=True)
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
            (record_id, payload, record_type, ts_utc, run_id),
        )
        self._conn.commit()

    def put_new(self, record_id: str, value: Any) -> None:
        self._ensure()
        record_type = value.get("record_type") if isinstance(value, dict) else None
        ts_utc = _extract_ts(value)
        run_id = value.get("run_id") if isinstance(value, dict) else None
        if not run_id:
            run_id = self._run_id
        payload = json.dumps(value, sort_keys=True)
        try:
            self._conn.execute(
                "INSERT INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
                (record_id, payload, record_type, ts_utc, run_id),
            )
            self._conn.commit()
        except Exception as exc:
            raise FileExistsError(f"Metadata record already exists: {record_id}") from exc

    def get(self, record_id: str, default: Any = None) -> Any:
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

    def query_time_window(self, start_ts: str | None, end_ts: str | None, limit: int | None = None) -> list[str]:
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

    def delete(self, record_id: str) -> bool:
        self._ensure()
        before = self._conn.total_changes
        self._conn.execute("DELETE FROM metadata WHERE id = ?", (record_id,))
        self._conn.commit()
        return self._conn.total_changes > before

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


class SqlCipherMetadataStore:
    def __init__(self, path: str | Path, keyring, run_id: str, fsync_policy: str) -> None:
        self._fallback: EncryptedMetadataStore | None = None
        available, _reason = _sqlcipher_available()
        if not available:
            self._fallback = EncryptedMetadataStore(path, keyring)
            self._store = None
            return
        key_id, root = keyring.active_key()
        key = derive_key(root, "metadata")
        self._store = _SQLCipherStore(path, key, run_id, fsync_policy)
        self._key_id = key_id

    def put(self, record_id: str, payload: dict[str, Any]) -> None:
        if self._fallback is not None:
            return self._fallback.put(record_id, payload)
        self._store.put(record_id, payload)

    def put_new(self, record_id: str, payload: dict[str, Any]) -> None:
        if self._fallback is not None:
            if hasattr(self._fallback, "put_new"):
                return self._fallback.put_new(record_id, payload)
            return self._fallback.put(record_id, payload)
        self._store.put_new(record_id, payload)

    def put_replace(self, record_id: str, payload: dict[str, Any]) -> None:
        if self._fallback is not None:
            if hasattr(self._fallback, "put_replace"):
                return self._fallback.put_replace(record_id, payload)
            return self._fallback.put(record_id, payload)
        self._store.put_replace(record_id, payload)

    def get(self, record_id: str, default: Any = None) -> Any:
        if self._fallback is not None:
            return self._fallback.get(record_id, default=default)
        return self._store.get(record_id, default=default)

    def keys(self) -> list[str]:
        if self._fallback is not None:
            return self._fallback.keys()
        return self._store.keys()

    def count(self) -> int:
        if self._fallback is not None and hasattr(self._fallback, "keys"):
            return len(self._fallback.keys())
        if self._fallback is not None:
            return 0
        return self._store.count()

    def query_time_window(self, start_ts: str | None, end_ts: str | None, limit: int | None = None) -> list[str]:
        if self._fallback is not None:
            return []
        return self._store.query_time_window(start_ts, end_ts, limit=limit)

    def delete(self, record_id: str) -> bool:
        if self._fallback is not None and hasattr(self._fallback, "delete"):
            return bool(self._fallback.delete(record_id))
        if self._fallback is not None:
            return False
        return self._store.delete(record_id)

    def rotate(self, new_root_key: bytes | None = None) -> None:
        if self._fallback is not None:
            if hasattr(self._fallback, "rotate"):
                return self._fallback.rotate(new_root_key)
            return None
        if new_root_key is None:
            return None
        new_key = derive_key(new_root_key, "metadata")
        self._store.rotate(new_key)

    def vacuum(self) -> None:
        if self._fallback is not None:
            if hasattr(self._fallback, "vacuum"):
                return self._fallback.vacuum()
            return None
        return self._store.vacuum()


def open_metadata_store(config: dict[str, Any]) -> SqlCipherMetadataStore:
    storage_cfg = config.get("storage", {})
    data_dir = storage_cfg.get("data_dir", "data")
    legacy_path = Path(data_dir) / "metadata" / "metadata.db"
    path = storage_cfg.get("metadata_path") or "data/metadata.db"
    if storage_cfg.get("metadata_path") and not Path(path).exists() and legacy_path.exists():
        path = str(legacy_path)
    fsync_policy = str(storage_cfg.get("fsync_policy", "none"))
    keyring = load_keyring(config)
    run_id = str(config.get("runtime", {}).get("run_id", "run"))
    return SqlCipherMetadataStore(path, keyring, run_id, fsync_policy)
