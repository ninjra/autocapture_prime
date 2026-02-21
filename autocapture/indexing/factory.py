"""Indexing helpers that respect local-only backends by default."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from autocapture.indexing.lexical_index import LexicalIndex
from autocapture.indexing.vector_index import LocalEmbedder, QdrantVectorIndex, VectorIndex


def _is_local_url(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).hostname
    return host in {"localhost", "127.0.0.1", "::1"}


def _resolve_under_data_dir(path: str, data_dir: str) -> str:
    """Resolve a (possibly-relative) index path deterministically under data_dir.

    Historically configs used paths like "data/lexical.db". If data_dir itself is
    ".../data", naive joining would produce ".../data/data/lexical.db". To keep
    backwards compatibility while removing CWD dependence, drop the redundant
    leading directory when it matches the data_dir basename.
    """

    if not path:
        return path
    p = Path(str(path))
    if p.is_absolute():
        return str(p)
    dd = Path(str(data_dir or "data"))
    parts = p.parts
    if parts and parts[0] == dd.name:
        p = Path(*parts[1:]) if len(parts) > 1 else Path()
    resolved = dd / p
    return os.fspath(resolved)


def build_indexes(
    config: dict[str, Any],
    *,
    logger: Callable[[str], None] | None = None,
    read_only: bool = False,
) -> tuple[LexicalIndex | None, VectorIndex | QdrantVectorIndex | None]:
    storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
    indexing_cfg = config.get("indexing", {}) if isinstance(config, dict) else {}
    data_dir = storage_cfg.get("data_dir", "data") if isinstance(storage_cfg, dict) else "data"
    lexical_path = storage_cfg.get("lexical_path", "data/lexical.db")
    vector_path = storage_cfg.get("vector_path", "data/vector.db")
    model_name = indexing_cfg.get("embedder_model")
    vector_backend = indexing_cfg.get("vector_backend", "sqlite")
    qcfg = indexing_cfg.get("qdrant", {}) if isinstance(indexing_cfg, dict) else {}
    qdrant_url = qcfg.get("url", "http://localhost:6333")
    qdrant_collection = qcfg.get("collection", "autocapture")

    lexical_path = _resolve_under_data_dir(str(lexical_path or ""), str(data_dir or "data"))
    vector_path = _resolve_under_data_dir(str(vector_path or ""), str(data_dir or "data"))

    lexical: LexicalIndex | None
    vector: VectorIndex | QdrantVectorIndex | None
    try:
        lexical = LexicalIndex(lexical_path, read_only=bool(read_only))
    except Exception as exc:
        lexical = None
        if logger:
            logger(f"index.lexical_init_failed: {exc}")

    try:
        if vector_backend == "qdrant" and not _is_local_url(qdrant_url):
            vector_backend = "sqlite"
        if vector_backend == "qdrant":
            vector = QdrantVectorIndex(qdrant_url, qdrant_collection, LocalEmbedder(model_name))
        else:
            vector = VectorIndex(vector_path, LocalEmbedder(model_name), read_only=bool(read_only))
    except Exception as exc:
        vector = None
        if logger:
            logger(f"index.vector_init_failed: {exc}")
    return lexical, vector
