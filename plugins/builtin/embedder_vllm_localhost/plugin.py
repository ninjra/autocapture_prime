"""Localhost-only embedder via an OpenAI-compatible server (eg vLLM).

This plugin is disabled by default and requires explicit localhost-network
permission via `plugins.permissions.localhost_allowed_plugin_ids`.
"""

from __future__ import annotations

from typing import Any

from autocapture.indexing.vector import LocalEmbedder
from autocapture_nx.inference.openai_compat import OpenAICompatClient
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class VllmEmbedder(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._base_url = str(cfg.get("base_url") or "http://127.0.0.1:8000").strip()
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 20.0)
        self._client: OpenAICompatClient | None = None
        self._fallback = LocalEmbedder(cfg.get("fallback_model"))

    def capabilities(self) -> dict[str, Any]:
        return {"embedder.text": self}

    def identity(self) -> dict[str, Any]:
        ident: dict[str, Any] = {
            "backend": "openai_compat",
            "base_url": self._base_url,
            "model": self._model or "",
        }
        try:
            ident["fallback"] = self._fallback.identity()
        except Exception:
            pass
        return ident

    def embed(self, text: str) -> list[float]:
        query = str(text or "")
        if not query.strip():
            return []
        if self._model is None:
            return self._fallback.embed(query)
        if self._client is None:
            try:
                self._client = OpenAICompatClient(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    timeout_s=self._timeout_s,
                )
            except Exception:
                self._client = None
                return self._fallback.embed(query)
        try:
            resp = self._client.embeddings({"model": self._model, "input": [query]})
            data = resp.get("data", [])
            if isinstance(data, list) and data:
                emb = data[0].get("embedding") if isinstance(data[0], dict) else None
                if isinstance(emb, list):
                    return [float(v) for v in emb]
        except Exception:
            return self._fallback.embed(query)
        return self._fallback.embed(query)


def create_plugin(plugin_id: str, context: PluginContext) -> VllmEmbedder:
    return VllmEmbedder(plugin_id, context)

