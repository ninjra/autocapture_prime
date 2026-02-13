"""ColBERT-style late-interaction reranker (hash fallback)."""

from __future__ import annotations

from typing import Any

from autocapture_nx.indexing.colbert import (
    ColbertSQLiteStore,
    HashTokenEmbedder,
    default_colbert_db_path,
    maxsim_score,
)
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class ColbertReranker(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        dim = int(cfg.get("dim") or 32)
        self._weight = float(cfg.get("weight") or 1.0)
        self._embedder = HashTokenEmbedder(dim=dim)
        db_path = str(cfg.get("db_path") or "").strip()
        self._store = ColbertSQLiteStore(db_path or default_colbert_db_path())

    def capabilities(self) -> dict[str, Any]:
        return {"retrieval.reranker": self}

    def identity(self) -> dict[str, Any]:
        return {"backend": "colbert.hash", "weight": self._weight, **self._embedder.identity()}

    def rerank(self, query: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q or not docs:
            return docs
        qmat = self._embedder.embed_query_tokens(q)
        ident = self._embedder.identity()
        digest = str(ident.get("embedder_digest") or "")
        if not digest:
            return docs
        doc_ids = []
        for d in docs:
            did = d.get("doc_id") or d.get("record_id")
            if did:
                doc_ids.append(str(did))
        rows = self._store.get_docs(doc_ids=doc_ids, embedder_digest=digest)
        scored: list[dict[str, Any]] = []
        for d in docs:
            did = str(d.get("doc_id") or d.get("record_id") or "")
            base = float(d.get("score", 0.0) or 0.0)
            row = rows.get(did)
            if row and row.get("blob") and int(row.get("dim") or 0) > 0:
                li = maxsim_score(qmat, row["blob"], dim=int(row.get("dim") or 0))
                score = base + (self._weight * float(li))
                scored.append({**d, "score": score, "rerank": {"colbert": li}})
            else:
                scored.append({**d, "score": base, "rerank": {"colbert": None}})
        scored.sort(key=lambda x: (-float(x.get("score", 0.0) or 0.0), str(x.get("doc_id") or "")))
        return scored


def create_plugin(plugin_id: str, context: PluginContext) -> ColbertReranker:
    return ColbertReranker(plugin_id, context)

