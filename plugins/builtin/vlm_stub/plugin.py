"""Local VLM plugin placeholder using BLIP/LLava style models (optional)."""

from __future__ import annotations

import os
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class VLMStub(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._model = None

    def capabilities(self) -> dict[str, Any]:
        return {"vision.extractor": self}

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from transformers import AutoProcessor, AutoModelForVision2Seq
        except Exception as exc:
            raise RuntimeError(f"Missing VLM dependency: {exc}")
        model_path = os.path.join("D:\\autocapture", "models", "vlm")
        processor = AutoProcessor.from_pretrained(model_path)
        model = AutoModelForVision2Seq.from_pretrained(model_path)
        self._model = (processor, model)
        return self._model

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        processor, model = self._load()
        from io import BytesIO
        from PIL import Image
        import torch

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            output = model.generate(**inputs, max_new_tokens=128)
        text = processor.batch_decode(output, skip_special_tokens=True)[0]
        return {"text": text, "layout": []}


def create_plugin(plugin_id: str, context: PluginContext) -> VLMStub:
    return VLMStub(plugin_id, context)
