"""Local embedding plugin with deterministic fallback."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture.indexing.vector import LocalEmbedder


class EmbedderBasic(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        model_name = None
        cfg = context.config if isinstance(context.config, dict) else {}
        indexing_cfg = cfg.get("indexing", {}) if isinstance(cfg.get("indexing", {}), dict) else {}
        model_name = indexing_cfg.get("embedder_model")
        self._embedder = LocalEmbedder(model_name)

    def capabilities(self) -> dict[str, Any]:
        return {"embedder.text": self}

    def embed(self, text: str) -> dict[str, Any]:
        vector = self._embedder.embed(text or "")
        identity = self._embedder.identity()
        model_id = str(identity.get("backend", "hash"))
        if identity.get("model_name"):
            model_id = f"{model_id}:{identity.get('model_name')}"
        return {"vector": vector, "model_id": model_id, "identity": identity}


def create_plugin(plugin_id: str, context: PluginContext) -> EmbedderBasic:
    return EmbedderBasic(plugin_id, context)


EmbedderLocal = EmbedderBasic
