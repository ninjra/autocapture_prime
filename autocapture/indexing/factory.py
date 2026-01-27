"""Indexing helpers that respect local-only backends by default."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import LocalEmbedder, QdrantVectorIndex, VectorIndex


def _is_local_url(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).hostname
    return host in {"localhost", "127.0.0.1", "::1"}


def build_indexes(
    config: dict[str, Any],
    *,
    logger: Callable[[str], None] | None = None,
) -> tuple[LexicalIndex | None, VectorIndex | QdrantVectorIndex | None]:
    storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
    indexing_cfg = config.get("indexing", {}) if isinstance(config, dict) else {}
    lexical_path = storage_cfg.get("lexical_path", "data/lexical.db")
    vector_path = storage_cfg.get("vector_path", "data/vector.db")
    model_name = indexing_cfg.get("embedder_model")
    vector_backend = indexing_cfg.get("vector_backend", "sqlite")
    qcfg = indexing_cfg.get("qdrant", {}) if isinstance(indexing_cfg, dict) else {}
    qdrant_url = qcfg.get("url", "http://localhost:6333")
    qdrant_collection = qcfg.get("collection", "autocapture")

    lexical: LexicalIndex | None
    vector: VectorIndex | QdrantVectorIndex | None
    try:
        lexical = LexicalIndex(lexical_path)
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
            vector = VectorIndex(vector_path, LocalEmbedder(model_name))
    except Exception as exc:
        vector = None
        if logger:
            logger(f"index.vector_init_failed: {exc}")
    return lexical, vector
