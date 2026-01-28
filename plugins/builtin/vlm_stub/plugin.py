"""Local VLM plugin with deterministic fallback."""

from __future__ import annotations

import json
from typing import Any

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.processing.sst.extract import (
    extract_charts,
    extract_code_blocks,
    extract_spreadsheets,
    extract_tables,
    parse_ui_elements,
)
from autocapture_nx.processing.sst.layout import assemble_layout
from autocapture_nx.processing.sst.utils import norm_text

from autocapture.ingest.ocr_basic import ocr_tokens_from_bytes


class VLMStub(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"vision.extractor": self}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        if not image_bytes:
            return {"text": json.dumps({"elements": [], "edges": []})}
        if not _PIL_AVAILABLE:
            return {"text": json.dumps({"elements": [], "edges": []})}
        try:
            image = Image.open(_as_bytes_io(image_bytes)).convert("RGB")
        except Exception:
            return {"text": json.dumps({"elements": [], "edges": []})}

        width, height = image.size
        tokens = _tokenize(image_bytes, width, height)
        lines, blocks = assemble_layout(
            tokens,
            line_y_threshold_px=12,
            block_gap_px=16,
            align_tolerance_px=12,
        )
        tables = extract_tables(
            tokens=tokens,
            state_id="vlm",
            min_rows=2,
            min_cols=2,
            max_cells=500,
            row_gap_px=10,
            col_gap_px=16,
        )
        spreadsheets = extract_spreadsheets(tokens=tokens, tables=tables, state_id="vlm", header_scan_rows=2)
        code_blocks = extract_code_blocks(
            tokens=tokens,
            text_lines=lines,
            state_id="vlm",
            min_keywords=2,
            image_rgb=None,
            detect_caret=False,
            detect_selection=False,
        )
        charts = extract_charts(tokens=tokens, state_id="vlm", min_ticks=2)
        element_graph = parse_ui_elements(
            state_id="vlm",
            frame_bbox=(0, 0, width, height),
            tokens=tokens,
            text_blocks=blocks,
            tables=tables,
            spreadsheets=spreadsheets,
            code_blocks=code_blocks,
            charts=charts,
        )
        elements = []
        for element in element_graph.get("elements", []):
            if element.get("type") == "window":
                continue
            elements.append(
                {
                    "type": element.get("type", "unknown"),
                    "bbox": element.get("bbox"),
                    "text": element.get("label"),
                    "interactable": bool(element.get("interactable", False)),
                    "state": element.get("state", {}) if isinstance(element.get("state", {}), dict) else {},
                }
            )
        payload = {"elements": elements, "edges": []}
        return {"text": json.dumps(payload), "layout": payload}


def create_plugin(plugin_id: str, context: PluginContext) -> VLMStub:
    return VLMStub(plugin_id, context)


def _tokenize(image_bytes: bytes, width: int, height: int) -> list[dict[str, Any]]:
    tokens = []
    for idx, token in enumerate(ocr_tokens_from_bytes(image_bytes)):
        token_id = encode_record_id_component(f"vlm-tok-{idx:05d}")
        bbox = _clamp_bbox(token.bbox, width, height)
        text = token.text
        tokens.append(
            {
                "token_id": token_id,
                "text": text,
                "norm_text": norm_text(text),
                "bbox": bbox,
                "confidence_bp": int(token.confidence * 10000),
                "source": "vlm",
            }
        )
    return tokens


def _clamp_bbox(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox
    x0 = max(0, min(int(x0), width))
    y0 = max(0, min(int(y0), height))
    x1 = max(0, min(int(x1), width))
    y1 = max(0, min(int(y1), height))
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return x0, y0, x1, y1


def _as_bytes_io(data: bytes):
    from io import BytesIO

    return BytesIO(data)
