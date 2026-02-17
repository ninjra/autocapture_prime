"""Localhost-only embedder via an OpenAI-compatible server (eg vLLM).

This plugin is disabled by default and requires explicit localhost-network
permission via `plugins.permissions.localhost_allowed_plugin_ids`.
"""

from __future__ import annotations

from typing import Any

from autocapture_nx.inference.openai_compat import OpenAICompatClient
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class VllmEmbedder(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._base_url_policy_error = ""
        try:
            self._base_url = enforce_external_vllm_base_url(cfg.get("base_url"))
        except Exception as exc:
            self._base_url = EXTERNAL_VLLM_BASE_URL
            self._base_url_policy_error = f"invalid_vllm_base_url:{type(exc).__name__}:{exc}"
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 20.0)
        self._strict_remote_only = bool(cfg.get("strict_remote_only", True))
        self._client: OpenAICompatClient | None = None
        self._last_error = ""

    def capabilities(self) -> dict[str, Any]:
        return {"embedder.text": self}

    def identity(self) -> dict[str, Any]:
        ident: dict[str, Any] = {
            "backend": "openai_compat",
            "base_url": self._base_url,
            "model": self._model or "",
            "strict_remote_only": bool(self._strict_remote_only),
        }
        if self._last_error:
            ident["last_error"] = self._last_error
        return ident

    def embed(self, text: str) -> list[float]:
        query = str(text or "")
        if not query.strip():
            return []
        if self._base_url_policy_error:
            self._last_error = self._base_url_policy_error
            return []
        if self._model is None:
            self._last_error = "embed_model_unset"
            return []
        if self._client is None:
            try:
                self._client = OpenAICompatClient(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    timeout_s=self._timeout_s,
                )
            except Exception as exc:
                self._client = None
                self._last_error = f"embed_client_init_failed:{type(exc).__name__}"
                return []
        try:
            resp = self._client.embeddings({"model": self._model, "input": [query]})
            data = resp.get("data", [])
            if isinstance(data, list) and data:
                emb = data[0].get("embedding") if isinstance(data[0], dict) else None
                if isinstance(emb, list):
                    self._last_error = ""
                    return [float(v) for v in emb]
            self._last_error = "embed_response_missing_embedding"
            return []
        except Exception as exc:
            self._last_error = f"embed_request_failed:{type(exc).__name__}"
            return []


def create_plugin(plugin_id: str, context: PluginContext) -> VllmEmbedder:
    return VllmEmbedder(plugin_id, context)
