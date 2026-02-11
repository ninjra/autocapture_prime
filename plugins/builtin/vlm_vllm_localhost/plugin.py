"""Localhost-only VLM via an OpenAI-compatible server (eg vLLM).

Falls back to deterministic heuristic layout extraction if the server/model
is not available. Disabled by default.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from PIL import Image

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

from autocapture.ingest.ocr_basic import ocr_tokens_from_bytes
from autocapture_nx.inference.openai_compat import OpenAICompatClient, image_bytes_to_data_url
from autocapture_nx.processing.sst.extract import (
    extract_charts,
    extract_code_blocks,
    extract_spreadsheets,
    extract_tables,
    parse_ui_elements,
)
from autocapture_nx.processing.sst.layout import assemble_layout
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


def _as_bytes_io(data: bytes):  # type: ignore[no-untyped-def]
    import io

    return io.BytesIO(data)


def _heuristic_layout(image_bytes: bytes) -> dict[str, Any]:
    if not image_bytes or not _PIL_AVAILABLE:
        return {"elements": [], "edges": [], "tables": [], "spreadsheets": [], "code_blocks": [], "charts": []}
    try:
        image = Image.open(_as_bytes_io(image_bytes)).convert("RGB")
    except Exception:
        return {"elements": [], "edges": [], "tables": [], "spreadsheets": [], "code_blocks": [], "charts": []}
    tokens = ocr_tokens_from_bytes(image_bytes)
    elements = parse_ui_elements(tokens, width=image.width, height=image.height)
    tables = extract_tables(tokens, width=image.width, height=image.height)
    spreadsheets = extract_spreadsheets(tokens, width=image.width, height=image.height)
    code_blocks = extract_code_blocks(tokens, width=image.width, height=image.height)
    charts = extract_charts(tokens, width=image.width, height=image.height)
    layout = assemble_layout(
        elements=elements,
        tables=tables,
        spreadsheets=spreadsheets,
        code_blocks=code_blocks,
        charts=charts,
        width=image.width,
        height=image.height,
    )
    return {
        "elements": layout.get("elements", []),
        "edges": layout.get("edges", []),
        "tables": tables,
        "spreadsheets": spreadsheets,
        "code_blocks": code_blocks,
        "charts": charts,
    }


class VllmVLM(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._base_url = str(cfg.get("base_url") or "http://127.0.0.1:8000").strip()
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 30.0)
        self._prompt = str(
            cfg.get("prompt")
            or "Describe the screen. Include key apps, notable text, and if audio is visible, the now-playing artist and track."
        ).strip()
        self._max_tokens = int(cfg.get("max_tokens") or 256)
        self._client: OpenAICompatClient | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"vision.extractor": self}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        layout = _heuristic_layout(image_bytes)
        payload: dict[str, Any] = {"layout": layout, "backend": "heuristic", "text": json.dumps(layout)}
        if not image_bytes or self._model is None:
            return payload
        if self._client is None:
            try:
                self._client = OpenAICompatClient(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    timeout_s=self._timeout_s,
                )
            except Exception as exc:
                payload["model_error"] = f"client_init_failed:{type(exc).__name__}:{exc}"
                self._client = None
                return payload
        try:
            data_url = image_bytes_to_data_url(image_bytes, content_type="image/png")
            req = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self._prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": self._max_tokens,
            }
            resp = self._client.chat_completions(req)
            choices = resp.get("choices", [])
            content = ""
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                content = str(msg.get("content") or "").strip()
            if content:
                payload["backend"] = "openai_compat"
                payload["caption"] = content
                payload["text_plain"] = content
                payload["model_id"] = self._model
        except Exception as exc:
            payload["model_error"] = f"vlm_failed:{type(exc).__name__}:{exc}"
        return payload


def create_plugin(plugin_id: str, context: PluginContext) -> VllmVLM:
    return VllmVLM(plugin_id, context)

