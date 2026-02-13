"""SQLite migration framework (forward-only by default).

Goals:
- Deterministic schema upgrades with explicit version pinning.
- Low-friction portability (SQLite/SQLCipher in data_dir).
- Rollback plan is "restore from backup bundle" unless an explicit down-migration exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Any], None]
    # Documentation-only: if a down-migration isn't provided, rollback is via restore.
    rollback_hint: str = "restore-from-backup"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_migrations_table(conn: Any, *, table: str = "schema_migrations") -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_utc TEXT NOT NULL
        )
        """
    )


def applied_versions(conn: Any, *, table: str = "schema_migrations") -> set[int]:
    ensure_migrations_table(conn, table=table)
    try:
        cur = conn.execute(f"SELECT version FROM {table} ORDER BY version")
        return {int(row[0]) for row in cur.fetchall() if row}
    except Exception:
        return set()


def record_baseline(conn: Any, *, version: int = 1, name: str = "baseline", table: str = "schema_migrations") -> None:
    """Record a baseline migration version if the table is empty."""

    ensure_migrations_table(conn, table=table)
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    row = cur.fetchone()
    count = int(row[0]) if row else 0
    if count:
        return
    conn.execute(
        f"INSERT INTO {table} (version, name, applied_utc) VALUES (?, ?, ?)",
        (int(version), str(name), _utc_now()),
    )


def apply_migrations(conn: Any, migrations: Iterable[Migration], *, table: str = "schema_migrations") -> list[int]:
    """Apply pending migrations in ascending version order.

    Returns the list of applied versions (empty if already up-to-date).
    """

    ensure_migrations_table(conn, table=table)
    existing = applied_versions(conn, table=table)
    pending = [m for m in migrations if int(m.version) not in existing]
    pending.sort(key=lambda m: int(m.version))
    applied: list[int] = []
    for mig in pending:
        mig.apply(conn)
        conn.execute(
            f"INSERT INTO {table} (version, name, applied_utc) VALUES (?, ?, ?)",
            (int(mig.version), str(mig.name), _utc_now()),
        )
        applied.append(int(mig.version))
    return applied

