"""Local reranker plugin using cross-encoder (optional)."""

from __future__ import annotations

import os
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class RerankerStub(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._model = None

    def capabilities(self) -> dict[str, Any]:
        return {"reranker": self}

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:
            raise RuntimeError(f"Missing reranker dependency: {exc}")
        model_path = os.path.join("D:\\autocapture", "models", "reranker")
        self._model = CrossEncoder(model_path)
        return self._model

    def rerank(self, items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        model = self._load()
        pairs = [(query, item.get("text", "")) for item in items]
        scores = model.predict(pairs)
        for item, score in zip(items, scores):
            item["rerank_score"] = float(score)
        return sorted(items, key=lambda i: -i.get("rerank_score", 0.0))


def create_plugin(plugin_id: str, context: PluginContext) -> RerankerStub:
    return RerankerStub(plugin_id, context)
