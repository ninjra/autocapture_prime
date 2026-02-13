"""GPU OCR stub plugin (placeholder for WSL2 offload workers)."""

from __future__ import annotations

from typing import Any


class OcrGpuStub:
    def __init__(self, plugin_id: str, context) -> None:  # noqa: ANN001
        self.plugin_id = plugin_id
        self.context = context

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def extract(self, frame_bytes: bytes) -> dict[str, Any]:
        # Placeholder: production implementation runs in WSL2 worker and returns
        # extracted text. Keep deterministic stub behavior here.
        return {"text": "", "engine": "gpu_stub"}


def create_plugin(plugin_id: str, context):  # noqa: ANN001
    return OcrGpuStub(plugin_id, context)

