"""DB/migration status helpers (OPS-06).

This is intentionally lightweight and read-only: it reports what exists and
basic sqlite pragmas so operators can spot drift across machines.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_file


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DbStatus:
    name: str
    path: str
    exists: bool
    size_bytes: int | None
    mtime_utc: str | None
    sha256: str | None
    sqlite_user_version: int | None
    sqlite_schema_version: int | None


def _sqlite_pragmas(path: Path) -> tuple[int | None, int | None]:
    try:
        con = sqlite3.connect(str(path))
        try:
            user_version = con.execute("PRAGMA user_version").fetchone()
            schema_version = con.execute("PRAGMA schema_version").fetchone()
        finally:
            con.close()
        uv = int(user_version[0]) if user_version else None
        sv = int(schema_version[0]) if schema_version else None
        return uv, sv
    except Exception:
        return None, None


def db_status_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    candidates = [
        ("metadata", storage.get("metadata_path", "data/metadata.db")),
        ("lexical", storage.get("lexical_path", "data/lexical.db")),
        ("vector", storage.get("vector_path", "data/vector.db")),
        ("state_tape", storage.get("state_tape_path", "data/state/state_tape.db")),
        ("state_vector", storage.get("state_vector_path", "data/state/state_vector.db")),
        ("audit", storage.get("audit_db_path", "data/audit.db")),
    ]
    rows: list[DbStatus] = []
    for name, raw in candidates:
        path = Path(str(raw))
        exists = path.exists()
        if exists:
            stat = path.stat()
            uv, sv = _sqlite_pragmas(path)
            rows.append(
                DbStatus(
                    name=name,
                    path=str(path),
                    exists=True,
                    size_bytes=int(stat.st_size),
                    mtime_utc=_utc_iso(stat.st_mtime),
                    sha256=sha256_file(path),
                    sqlite_user_version=uv,
                    sqlite_schema_version=sv,
                )
            )
        else:
            rows.append(
                DbStatus(
                    name=name,
                    path=str(path),
                    exists=False,
                    size_bytes=None,
                    mtime_utc=None,
                    sha256=None,
                    sqlite_user_version=None,
                    sqlite_schema_version=None,
                )
            )
    return {"ok": True, "dbs": [asdict(row) for row in rows]}

