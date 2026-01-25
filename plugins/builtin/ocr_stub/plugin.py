"""Local OCR plugin using optional pytesseract."""

from __future__ import annotations

import os
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class OCRLocal(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        try:
            import pytesseract
            from PIL import Image
        except Exception as exc:
            raise RuntimeError(f"Missing OCR dependency: {exc}")
        from io import BytesIO

        if not image_bytes:
            raise RuntimeError("Missing OCR input bytes")
        try:
            img = Image.open(BytesIO(image_bytes))
        except Exception as exc:
            raise RuntimeError(f"Invalid OCR image bytes: {exc}")
        text = pytesseract.image_to_string(img)
        return {"text": text}


def create_plugin(plugin_id: str, context: PluginContext) -> OCRLocal:
    return OCRLocal(plugin_id, context)
