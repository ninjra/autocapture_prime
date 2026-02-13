"""GPU OCR placeholder plugin.

The adversarial redesign traceability expects `plugins/builtin/*_gpu`.
This implementation is disabled by default and exists to make GPU routing
opt-in without breaking local-only defaults.
"""

from __future__ import annotations

from typing import Any


class OcrGpu:
    def __init__(self, plugin_id: str, context) -> None:  # noqa: ANN001
        self.plugin_id = plugin_id
        self.context = context

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def extract(self, frame_bytes: bytes) -> dict[str, Any]:
        return {"text": "", "engine": "gpu_placeholder"}


def create_plugin(plugin_id: str, context):  # noqa: ANN001
    return OcrGpu(plugin_id, context)

