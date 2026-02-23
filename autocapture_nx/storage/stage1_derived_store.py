"""Stage1 derived-store helpers (separate from ingest metadata DB)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


def default_stage1_derived_db_path(dataroot: str | Path) -> Path:
    root = Path(str(dataroot)).expanduser()
    return root / "derived" / "stage1_derived.db"


def resolve_stage1_derived_db_path(config: dict[str, Any] | None, *, dataroot_hint: str | None = None) -> Path | None:
    cfg = config if isinstance(config, dict) else {}
    storage_cfg = cfg.get("storage") if isinstance(cfg.get("storage"), dict) else {}
    stage1_cfg = storage_cfg.get("stage1_derived") if isinstance(storage_cfg.get("stage1_derived"), dict) else {}
    enabled = bool(stage1_cfg.get("enabled", False))
    if not enabled:
        return None
    explicit = str(
        stage1_cfg.get("db_path")
        or storage_cfg.get("stage1_derived_db_path")
        or ""
    ).strip()
    if explicit:
        return Path(explicit).expanduser()
    dataroot = str(
        storage_cfg.get("data_dir")
        or dataroot_hint
        or os.environ.get("AUTOCAPTURE_DATA_DIR")
        or "data"
    ).strip()
    return default_stage1_derived_db_path(dataroot)


class Stage1DerivedSqliteStore:
    """Minimal JSON-record store backed by SQLite metadata table."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(str(db_path)).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    id TEXT PRIMARY KEY,
                    record_type TEXT,
                    ts_utc TEXT,
                    payload TEXT,
                    run_id TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_record_type ON metadata(record_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_ts_utc ON metadata(ts_utc)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_run_id ON metadata(run_id)")
            conn.commit()
            self._conn = conn
        return self._conn

    def _decode(self, row: sqlite3.Row | tuple[Any, ...] | None, default: Any = None) -> Any:
        if row is None:
            return default
        if isinstance(row, sqlite3.Row):
            payload = row["payload"]
        else:
            payload = row[0] if row else None
        if not isinstance(payload, str) or not payload.strip():
            return default
        try:
            parsed = json.loads(payload)
        except Exception:
            return default
        return parsed if isinstance(parsed, dict) else default

    def get(self, record_id: str, default: Any = None) -> Any:
        with self._lock:
            conn = self._ensure()
            row = conn.execute("SELECT payload FROM metadata WHERE id = ?", (str(record_id),)).fetchone()
            return self._decode(row, default=default)

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True)
        ts_utc = str(value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc") or "")
        run_id = str(value.get("run_id") or "")
        record_type = str(value.get("record_type") or "")
        with self._lock:
            conn = self._ensure()
            try:
                conn.execute(
                    "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
                    (str(record_id), record_type, ts_utc, payload, run_id),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise FileExistsError(str(record_id)) from exc

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True)
        ts_utc = str(value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc") or "")
        run_id = str(value.get("run_id") or "")
        record_type = str(value.get("record_type") or "")
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT OR REPLACE INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
                (str(record_id), record_type, ts_utc, payload, run_id),
            )
            conn.commit()

    def put_replace(self, record_id: str, value: dict[str, Any]) -> None:
        self.put(record_id, value)

    def keys(self) -> list[str]:
        with self._lock:
            conn = self._ensure()
            rows = conn.execute("SELECT id FROM metadata ORDER BY id").fetchall()
        return [str(row[0]) for row in rows]

    def count(self, *, record_type: str | None = None) -> int:
        with self._lock:
            conn = self._ensure()
            if record_type:
                row = conn.execute("SELECT COUNT(*) FROM metadata WHERE record_type = ?", (str(record_type),)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM metadata").fetchone()
        return int(row[0]) if row else 0

    @property
    def db_path(self) -> Path:
        return self._db_path


class Stage1OverlayStore:
    """Read-through overlay: reads derived first, falls back to ingest metadata."""

    def __init__(self, *, metadata_read: Any, derived_write: Stage1DerivedSqliteStore) -> None:
        self._metadata_read = metadata_read
        self._derived_write = derived_write

    def get(self, record_id: str, default: Any = None) -> Any:
        row = self._derived_write.get(record_id, None)
        if isinstance(row, dict):
            return row
        if self._metadata_read is None or not hasattr(self._metadata_read, "get"):
            return default
        return self._metadata_read.get(record_id, default)

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        self._derived_write.put_new(record_id, value)

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        self._derived_write.put(record_id, value)

    def put_replace(self, record_id: str, value: dict[str, Any]) -> None:
        self._derived_write.put_replace(record_id, value)

    def keys(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        if self._metadata_read is not None and hasattr(self._metadata_read, "keys"):
            try:
                for key in self._metadata_read.keys():
                    token = str(key)
                    if token in seen:
                        continue
                    seen.add(token)
                    out.append(token)
            except Exception:
                pass
        try:
            for key in self._derived_write.keys():
                token = str(key)
                if token in seen:
                    continue
                seen.add(token)
                out.append(token)
        except Exception:
            pass
        out.sort()
        return out


def build_stage1_overlay_store(
    *,
    config: dict[str, Any] | None,
    metadata: Any,
    logger: Any | None = None,
    dataroot_hint: str | None = None,
) -> tuple[Any, Stage1DerivedSqliteStore | None]:
    if metadata is None:
        return metadata, None
    path = resolve_stage1_derived_db_path(config, dataroot_hint=dataroot_hint)
    if path is None:
        return metadata, None
    try:
        derived = Stage1DerivedSqliteStore(path)
        overlay = Stage1OverlayStore(metadata_read=metadata, derived_write=derived)
        return overlay, derived
    except Exception as exc:
        if logger is not None:
            try:
                logger.log(
                    "stage1.derived_store.error",
                    {"error": f"{type(exc).__name__}:{exc}", "db_path": str(path)},
                )
            except Exception:
                pass
        return metadata, None
