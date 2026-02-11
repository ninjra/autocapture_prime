"""Nemotron OCR plugin (optional torch backend).

This is a placeholder integration point for NVIDIA Nemotron OCR checkpoints.
It fails closed (returns empty text) when dependencies/models are missing.
"""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class NemotronOCR(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._model_id = str(cfg.get("model_id") or "").strip()
        self._device = str(cfg.get("device") or "cuda").strip()
        self._loaded = False
        self._error: str | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def extract(self, frame_bytes: bytes) -> dict[str, Any]:
        if not frame_bytes:
            return {"text": "", "engine": "nemotron", "model_id": self._model_id, "error": "empty_frame"}
        # Optional dependency guard.
        try:
            import torch  # noqa: F401
            from transformers import AutoProcessor, AutoModelForVision2Seq  # noqa: F401

            _ = AutoProcessor
            _ = AutoModelForVision2Seq
        except Exception as exc:
            return {
                "text": "",
                "engine": "nemotron",
                "model_id": self._model_id,
                "error": f"deps_missing:{type(exc).__name__}",
            }

        # TODO: Real Nemotron OCR inference.
        # Keep deterministic placeholder to validate routing without crashing.
        return {"text": "", "engine": "nemotron", "model_id": self._model_id, "notice": "not_configured"}


def create_plugin(plugin_id: str, context: PluginContext) -> NemotronOCR:
    return NemotronOCR(plugin_id, context)

