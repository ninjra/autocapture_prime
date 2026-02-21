"""Resilient SQLite read helpers for sidecar-managed, high-churn DBs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _looks_transient_sqlite_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return any(
        token in text
        for token in (
            "database is locked",
            "disk i/o error",
            "database disk image is malformed",
            "unable to open database file",
            "readonly database",
            "ioerr",
            "busy",
        )
    )


def _snapshot_path_for(db_path: Path, *, snapshot_root: str | Path = "/tmp/autocapture_sqlite_snapshots") -> Path:
    root = Path(snapshot_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{db_path.stem}.{_utc_compact()}.snapshot.db"


def create_sqlite_read_snapshot(db_path: str | Path, *, snapshot_root: str | Path = "/tmp/autocapture_sqlite_snapshots") -> Path:
    """Create a consistent sqlite snapshot using sqlite backup API."""

    src_path = Path(db_path).expanduser()
    if not src_path.exists():
        raise FileNotFoundError(str(src_path))
    snapshot_path = _snapshot_path_for(src_path, snapshot_root=snapshot_root)
    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=2.0)
        dst_conn = sqlite3.connect(str(snapshot_path), timeout=2.0)
        src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()
    return snapshot_path


def open_sqlite_reader(
    db_path: str | Path,
    *,
    prefer_snapshot: bool = True,
    force_snapshot: bool = False,
) -> tuple[sqlite3.Connection, dict[str, Any]]:
    """Open a read-only sqlite connection with optional snapshot fallback."""

    src_path = Path(db_path).expanduser()
    if not src_path.exists():
        raise FileNotFoundError(str(src_path))

    if force_snapshot:
        snap = create_sqlite_read_snapshot(src_path)
        conn = sqlite3.connect(f"file:{snap}?mode=ro&immutable=1", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn, {
            "mode": "snapshot",
            "source_path": str(src_path),
            "snapshot_path": str(snap),
        }

    try:
        conn = sqlite3.connect(f"file:{src_path}?mode=ro&immutable=1", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn, {
            "mode": "direct_ro",
            "source_path": str(src_path),
            "snapshot_path": "",
        }
    except Exception as exc:
        if not prefer_snapshot or not _looks_transient_sqlite_error(exc):
            raise
        snap = create_sqlite_read_snapshot(src_path)
        conn = sqlite3.connect(f"file:{snap}?mode=ro&immutable=1", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn, {
            "mode": "snapshot_fallback",
            "source_path": str(src_path),
            "snapshot_path": str(snap),
            "fallback_error": f"{type(exc).__name__}:{exc}",
        }
