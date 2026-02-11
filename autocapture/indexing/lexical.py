"""Lexical indexing using SQLite FTS5."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

from autocapture.indexing.manifest import bump_manifest, update_manifest_digest, manifest_path
from autocapture_nx.storage.migrations import record_baseline


_STOPWORDS = {
    # Keep this small and stable; the goal is to avoid "AND-ing" away recall for
    # natural-language questions, not to do full NLP.
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "many",
    "me",
    "my",
    "of",
    "on",
    "open",
    "or",
    "the",
    "to",
    "was",
    "we",
    "what",
    "when",
    "where",
    "who",
    "with",
    "you",
    "your",
}


def _fts_expr(query: str) -> str:
    """Convert arbitrary user text into a safe, FTS5-compatible MATCH expression."""

    raw = str(query or "").strip().lower()
    if not raw:
        return ""

    tokens = [t for t in re.findall(r"[a-z0-9]+", raw) if t]
    if not tokens:
        return ""

    filtered: list[str] = [t for t in tokens if t not in _STOPWORDS and len(t) > 1]
    if not filtered:
        filtered = tokens

    seen: set[str] = set()
    uniq: list[str] = []
    for tok in filtered:
        if tok in seen:
            continue
        seen.add(tok)
        uniq.append(tok)

    if not uniq:
        return ""
    if len(uniq) == 1:
        return f"\"{uniq[0]}\""
    # Use OR for recall; rank by bm25 and then deterministic tie-breakers upstream.
    return " OR ".join(f"\"{tok}\"" for tok in uniq[:12])


class LexicalIndex:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self._read_only = bool(read_only)
        if self._read_only:
            if not self.path.exists():
                raise FileNotFoundError(str(self.path))
            # Open read-only so sandboxed plugin hosts with filesystem=read can query.
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path)
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(doc_id, content)")
            # PERF-02: track per-doc digests to avoid redundant re-indexing.
            self._conn.execute("CREATE TABLE IF NOT EXISTS indexed (doc_id TEXT PRIMARY KEY, digest TEXT)")
            try:
                record_baseline(self._conn, version=1, name="lexical.baseline")
            except Exception:
                pass
            self._conn.commit()
        self._identity_cache: dict[str, Any] | None = None
        self._identity_mtime: float | None = None
        self._manifest_mtime: float | None = None

    def index(self, doc_id: str, content: str) -> None:
        if self._read_only:
            raise PermissionError("LexicalIndex is read-only")
        self._conn.execute("DELETE FROM fts WHERE doc_id = ?", (doc_id,))
        self._conn.execute("INSERT INTO fts(doc_id, content) VALUES (?, ?)", (doc_id, content))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._conn.execute("REPLACE INTO indexed (doc_id, digest) VALUES (?, ?)", (doc_id, digest))
        self._conn.commit()
        try:
            bump_manifest(self.path, "lexical")
        except Exception:
            pass

    def index_if_changed(self, doc_id: str, content: str) -> bool:
        """Index only when the content digest has changed."""
        if self._read_only:
            raise PermissionError("LexicalIndex is read-only")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            cur = self._conn.execute("SELECT digest FROM indexed WHERE doc_id = ?", (doc_id,))
            row = cur.fetchone()
            if row and str(row[0]) == digest:
                return False
        except Exception:
            # If the digest table is unavailable/corrupt, fall back to full index.
            pass
        self.index(doc_id, content)
        return True

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM fts")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def query(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        expr = _fts_expr(text)
        if not expr:
            return []
        cur = self._conn.execute(
            "SELECT doc_id, snippet(fts, 1, '[', ']', '...', 10), bm25(fts) "
            "FROM fts WHERE fts MATCH ? ORDER BY bm25(fts), doc_id LIMIT ?",
            (expr, limit),
        )
        hits = []
        for doc_id, snippet, bm25_score in cur.fetchall():
            if isinstance(doc_id, (bytes, bytearray)):
                try:
                    doc_id = doc_id.decode("utf-8", errors="replace")
                except Exception:
                    doc_id = str(doc_id)
            else:
                doc_id = str(doc_id)
            if isinstance(snippet, (bytes, bytearray)):
                try:
                    snippet = snippet.decode("utf-8", errors="replace")
                except Exception:
                    snippet = str(snippet)
            else:
                snippet = str(snippet) if snippet is not None else ""
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
