"""Local embedding plugin using optional sentence-transformers or ONNX."""

from __future__ import annotations

import os
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class EmbedderLocal(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._model = None

    def capabilities(self) -> dict[str, Any]:
        return {"embedder.text": self}

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(f"Missing embedder dependency: {exc}")
        model_path = os.path.join("D:\\autocapture", "models", "embeddings")
        if not os.path.isdir(model_path):
            raise RuntimeError(f"Missing embedder model files at {model_path}")
        try:
            self._model = SentenceTransformer(model_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to load embedder model at {model_path}: {exc}")
        return self._model

    def embed(self, text: str) -> dict[str, Any]:
        model = self._load()
        vec = model.encode([text])[0]
        return {"vector": vec.tolist(), "model_id": "local_sentence_transformers"}


def create_plugin(plugin_id: str, context: PluginContext) -> EmbedderLocal:
    return EmbedderLocal(plugin_id, context)
