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
        self._conn.execute("INSERT INTO fts(doc_id, content) VALUES (?, ?)", (doc_id, content))
        self._conn.commit()

    def query(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT doc_id, snippet(fts, 1, '[', ']', '...', 10) FROM fts WHERE fts MATCH ? LIMIT ?", (text, limit))
        return [{"doc_id": row[0], "snippet": row[1]} for row in cur.fetchall()]


def create_lexical_index(plugin_id: str) -> LexicalIndex:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    path = config.get("storage", {}).get("lexical_path", "data/lexical.db")
    return LexicalIndex(path)
