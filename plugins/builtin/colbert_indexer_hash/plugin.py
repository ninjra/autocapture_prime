"""Hash-based ColBERT-style late-interaction indexer (fallback).

This provides the "late interaction index path" even when no heavyweight
token-embedder model is installed. It is intended as a stable integration
point: replace the embedder with a real model (eg Nemotron CoLEmbed v2) via
another plugin without changing downstream retrieval.
"""

from __future__ import annotations

from typing import Any

from autocapture_nx.indexing.colbert import (
    ColbertSQLiteStore,
    HashTokenEmbedder,
    default_colbert_db_path,
)
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.storage.facts_ndjson import append_fact_line

def _facts_cfg() -> dict[str, Any]:
    import os
    from pathlib import Path

    data_dir = os.getenv("AUTOCAPTURE_DATA_DIR", "").strip()
    if not data_dir:
        data_dir = "data"
    return {"storage": {"data_dir": str(Path(data_dir).expanduser().absolute())}}


class ColbertIndexer(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        dim = int(cfg.get("dim") or 32)
        self._embedder = HashTokenEmbedder(dim=dim)
        db_path = str(cfg.get("db_path") or "").strip()
        self._store = ColbertSQLiteStore(db_path or default_colbert_db_path())

    def capabilities(self) -> dict[str, Any]:
        return {"index.postprocess": self}

    def identity(self) -> dict[str, Any]:
        return {"backend": "colbert.hash", **self._embedder.identity()}

    def process_doc(self, doc_id: str, text: str) -> dict[str, Any]:
        did = str(doc_id or "").strip()
        txt = str(text or "")
        if not did or not txt.strip():
            return {"ok": False, "error": "missing_doc_or_text"}
        text_sha = sha256_text(txt)
        emb = self._embedder.embed_tokens(txt)
        ident = self._embedder.identity()
        inserted = False
        if emb.tokens:
            inserted = self._store.insert_doc(
                doc_id=did,
                embedder_identity=ident,
                embeddings=emb,
                text_sha256=text_sha,
                provenance={"plugin_id": self.plugin_id, "embedder": ident},
            )
        payload = {
            "schema_version": 1,
            "record_type": "derived.index.colbert",
            "doc_id": did,
            "embedder_id": ident.get("embedder_id"),
            "embedder_digest": ident.get("embedder_digest"),
            "token_count": int(len(emb.tokens)),
            "dim": int(ident.get("dim") or emb.dim),
            "inserted": bool(inserted),
            "text_sha256": text_sha,
        }
        try:
            _ = append_fact_line(_facts_cfg(), rel_path="colbert_index.ndjson", payload=payload)
        except Exception:
            pass
        return {"ok": True, "inserted": bool(inserted), "token_count": int(len(emb.tokens))}


def create_plugin(plugin_id: str, context: PluginContext) -> ColbertIndexer:
    return ColbertIndexer(plugin_id, context)
