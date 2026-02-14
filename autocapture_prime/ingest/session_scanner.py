from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SessionCandidate:
    session_id: str
    session_dir: Path
    manifest_path: Path


class SessionScanner:
    """Enumerate complete spool sessions and track processed state."""

    def __init__(self, spool_root: Path, state_db: Path) -> None:
        self.spool_root = Path(spool_root)
        self.state_db = Path(state_db)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.state_db)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_sessions (
                  session_id TEXT PRIMARY KEY,
                  session_dir TEXT NOT NULL,
                  processed_at_utc TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _iter_session_dirs(self) -> list[Path]:
        if not self.spool_root.exists():
            return []
        paths = [p for p in self.spool_root.glob("session_*") if p.is_dir()]
        return sorted(paths)

    def list_complete(self) -> list[SessionCandidate]:
        candidates: list[SessionCandidate] = []
        for session_dir in self._iter_session_dirs():
            manifest = session_dir / "manifest.json"
            complete = session_dir / "COMPLETE.json"
            if not manifest.exists() or not complete.exists():
                continue
            session_id = session_dir.name.removeprefix("session_")
            candidates.append(
                SessionCandidate(
                    session_id=session_id,
                    session_dir=session_dir,
                    manifest_path=manifest,
                )
            )
        return candidates

    def list_pending(self) -> list[SessionCandidate]:
        with self._connect() as conn:
            seen = {row[0] for row in conn.execute("SELECT session_id FROM processed_sessions")}
        return [item for item in self.list_complete() if item.session_id not in seen]

    def mark_processed(self, session: SessionCandidate) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_sessions (session_id, session_dir, processed_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  session_dir=excluded.session_dir,
                  processed_at_utc=excluded.processed_at_utc
                """,
                (session.session_id, str(session.session_dir), now),
            )
            conn.commit()
