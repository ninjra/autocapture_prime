"""DB/migration status helpers (OPS-06).

This is intentionally lightweight and read-only: it reports what exists and
basic sqlite pragmas so operators can spot drift across machines.
"""

from __future__ import annotations

import sqlite3
import time
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
    inode: int | None
    mtime_ns: int | None
    stable: bool | None
    churn_events: int | None


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


def _file_signature(path: Path) -> dict[str, int] | None:
    try:
        stat = path.stat()
    except Exception:
        return None
    return {
        "inode": int(getattr(stat, "st_ino", 0) or 0),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
    }


def _sample_stability(path: Path, *, sample_count: int, poll_interval_ms: int) -> tuple[bool | None, int | None]:
    count = max(1, min(32, int(sample_count)))
    interval_ms = max(0, min(2000, int(poll_interval_ms)))
    signatures: list[dict[str, int]] = []
    for idx in range(count):
        sig = _file_signature(path)
        if sig is None:
            break
        signatures.append(sig)
        if idx + 1 < count and interval_ms > 0:
            time.sleep(float(interval_ms) / 1000.0)
    if not signatures:
        return None, None
    churn_events = 0
    prev = signatures[0]
    for sig in signatures[1:]:
        if sig != prev:
            churn_events += 1
        prev = sig
    return bool(churn_events == 0), int(churn_events)


def metadata_db_stability_snapshot(
    config: dict[str, Any],
    *,
    sample_count: int = 3,
    poll_interval_ms: int = 250,
) -> dict[str, Any]:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    path = Path(str(storage.get("metadata_path", "data/metadata.db")))
    exists = path.exists()
    out: dict[str, Any] = {
        "ok": bool(exists),
        "name": "metadata",
        "path": str(path),
        "exists": bool(exists),
        "sample_count": int(max(1, min(32, int(sample_count)))),
        "poll_interval_ms": int(max(0, min(2000, int(poll_interval_ms)))),
        "stable": None,
        "churn_events": None,
        "inode": None,
        "size_bytes": None,
        "mtime_ns": None,
    }
    if not exists:
        out["reason"] = "metadata_db_missing"
        return out
    sig = _file_signature(path)
    if isinstance(sig, dict):
        out["inode"] = int(sig.get("inode", 0))
        out["size_bytes"] = int(sig.get("size_bytes", 0))
        out["mtime_ns"] = int(sig.get("mtime_ns", 0))
    stable, churn_events = _sample_stability(
        path,
        sample_count=int(out["sample_count"]),
        poll_interval_ms=int(out["poll_interval_ms"]),
    )
    out["stable"] = stable
    out["churn_events"] = churn_events
    out["ok"] = bool(exists and (stable is not False))
    if stable is False:
        out["reason"] = "metadata_db_churn_detected"
    return out


def db_status_snapshot(
    config: dict[str, Any],
    *,
    include_hash: bool = True,
    include_pragmas: bool = True,
    include_stability: bool = False,
    stability_samples: int = 2,
    stability_poll_interval_ms: int = 100,
) -> dict[str, Any]:
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
            uv, sv = (None, None)
            if include_pragmas:
                uv, sv = _sqlite_pragmas(path)
            stable = None
            churn_events = None
            if include_stability:
                stable, churn_events = _sample_stability(
                    path,
                    sample_count=stability_samples,
                    poll_interval_ms=stability_poll_interval_ms,
                )
            rows.append(
                DbStatus(
                    name=name,
                    path=str(path),
                    exists=True,
                    size_bytes=int(stat.st_size),
                    mtime_utc=_utc_iso(stat.st_mtime),
                    sha256=sha256_file(path) if include_hash else None,
                    sqlite_user_version=uv,
                    sqlite_schema_version=sv,
                    inode=int(getattr(stat, "st_ino", 0) or 0),
                    mtime_ns=int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                    stable=stable,
                    churn_events=churn_events,
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
                    inode=None,
                    mtime_ns=None,
                    stable=None,
                    churn_events=None,
                )
            )
    return {"ok": True, "dbs": [asdict(row) for row in rows]}
