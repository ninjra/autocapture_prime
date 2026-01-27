"""Lexical indexing using SQLite FTS5."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from autocapture.indexing.manifest import bump_manifest, update_manifest_digest, manifest_path


class LexicalIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(doc_id, content)")
        self._conn.commit()
        self._identity_cache: dict[str, Any] | None = None
        self._identity_mtime: float | None = None
        self._manifest_mtime: float | None = None

    def index(self, doc_id: str, content: str) -> None:
        self._conn.execute("DELETE FROM fts WHERE doc_id = ?", (doc_id,))
        self._conn.execute("INSERT INTO fts(doc_id, content) VALUES (?, ?)", (doc_id, content))
        self._conn.commit()
        try:
            bump_manifest(self.path, "lexical")
        except Exception:
            pass

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM fts")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def query(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT doc_id, snippet(fts, 1, '[', ']', '...', 10), bm25(fts) "
            "FROM fts WHERE fts MATCH ? ORDER BY bm25(fts), doc_id LIMIT ?",
            (text, limit),
        )
        hits = []
        for doc_id, snippet, bm25_score in cur.fetchall():
            raw_score = float(bm25_score) if bm25_score is not None else 0.0
            score = 1.0 / (1.0 + max(raw_score, 0.0))
            hits.append({"doc_id": doc_id, "snippet": snippet, "score": score})
        return hits

    def identity(self) -> dict[str, Any]:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        try:
            manifest_mtime = manifest_path(self.path).stat().st_mtime
        except FileNotFoundError:
            manifest_mtime = None
        if (
            self._identity_cache is None
            or self._identity_mtime != mtime
            or self._manifest_mtime != manifest_mtime
        ):
            digest = None
            if self.path.exists():
                from autocapture_nx.kernel.hashing import sha256_file

                digest = sha256_file(self.path)
            manifest = update_manifest_digest(self.path, "lexical", digest)
            self._identity_cache = {
                "backend": "sqlite_fts5",
                "path": str(self.path),
                "digest": digest,
                "version": int(manifest.version),
                "manifest_path": str(manifest_path(self.path)),
            }
            self._identity_mtime = mtime
            self._manifest_mtime = manifest_mtime
        return dict(self._identity_cache)


def create_lexical_index(plugin_id: str) -> LexicalIndex:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    path = config.get("storage", {}).get("lexical_path", "data/lexical.db")
    return LexicalIndex(path)
