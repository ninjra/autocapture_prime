"""Local OCR plugin with deterministic fallback and optional Tesseract support."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture.ingest.ocr_basic import ocr_text_from_bytes, ocr_tokens_from_bytes


class OCRLocal(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        self._tesseract_cmd = models_cfg.get("ocr_path")
        self._lang = models_cfg.get("ocr_lang")
        self._psm = models_cfg.get("ocr_psm")
        self._oem = models_cfg.get("ocr_oem")

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def extract_tokens(self, image_bytes: bytes) -> dict[str, Any]:
        if not image_bytes:
            return {"tokens": []}
        tokens = ocr_tokens_from_bytes(
            image_bytes,
            lang=self._lang,
            psm=self._psm,
            oem=self._oem,
            tesseract_cmd=self._tesseract_cmd,
        )
        output = []
        for token in tokens:
            output.append(
                {
                    "text": token.text,
                    "bbox": token.bbox,
                    "confidence": float(token.confidence),
                }
            )
        return {"tokens": output}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        if not image_bytes:
            return {"text": "", "tokens": []}
        tokens = self.extract_tokens(image_bytes).get("tokens", [])
        text = ocr_text_from_bytes(
            image_bytes,
            lang=self._lang,
            psm=self._psm,
            oem=self._oem,
            tesseract_cmd=self._tesseract_cmd,
        )
        return {"text": text, "tokens": tokens}


def create_plugin(plugin_id: str, context: PluginContext) -> OCRLocal:
    return OCRLocal(plugin_id, context)
