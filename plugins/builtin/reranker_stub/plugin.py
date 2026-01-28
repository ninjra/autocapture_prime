"""Local reranker plugin with deterministic fallback."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture.retrieval.rerank import Reranker


class RerankerStub(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._fallback = Reranker()
        self._cross_encoder = None
        cfg = context.config if isinstance(context.config, dict) else {}
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        self._model_path = models_cfg.get("reranker_path")

    def capabilities(self) -> dict[str, Any]:
        return {"reranker": self}

    def _load(self):
        if self._cross_encoder is not None:
            return self._cross_encoder
        if not self._model_path:
            return None
        try:
            from sentence_transformers import CrossEncoder
        except Exception:
            return None
        try:
            self._cross_encoder = CrossEncoder(self._model_path)
        except Exception:
            self._cross_encoder = None
        return self._cross_encoder

    def rerank(self, items: list[dict[str, Any]] | str, query: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(items, str):
            query_text = items
            docs = list(query) if isinstance(query, list) else []
        else:
            docs = list(items)
            query_text = str(query)
        model = self._load()
        if model is None:
            return self._fallback.rerank(query_text, docs)
        pairs = [(query_text, doc.get("text", "")) for doc in docs]
        try:
            scores = model.predict(pairs)
        except Exception:
            return self._fallback.rerank(query_text, docs)
        for doc, score in zip(docs, scores):
            doc["rerank_score"] = float(score)
        return sorted(docs, key=lambda d: -d.get("rerank_score", 0.0))


def create_plugin(plugin_id: str, context: PluginContext) -> RerankerStub:
    return RerankerStub(plugin_id, context)
