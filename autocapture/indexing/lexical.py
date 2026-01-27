"""Lexical indexing using SQLite FTS5."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class LexicalIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(doc_id, content)")
        self._conn.commit()

    def index(self, doc_id: str, content: str) -> None:
        self._conn.execute("DELETE FROM fts WHERE doc_id = ?", (doc_id,))
        self._conn.execute("INSERT INTO fts(doc_id, content) VALUES (?, ?)", (doc_id, content))
        self._conn.commit()

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


def create_lexical_index(plugin_id: str) -> LexicalIndex:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    path = config.get("storage", {}).get("lexical_path", "data/lexical.db")
    return LexicalIndex(path)
