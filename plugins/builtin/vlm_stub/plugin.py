"""Local VLM plugin with deterministic fallback and optional model inference."""

from __future__ import annotations

import json
import os
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
        cfg = context.config if isinstance(context.config, dict) else {}
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        self._model_path = models_cfg.get("vlm_path")
        self._prompt = str(models_cfg.get("vlm_prompt") or "Describe the screen contents concisely.")
        self._max_new_tokens = int(models_cfg.get("vlm_max_new_tokens") or 160)
        self._backend = "heuristic"
        self._pipeline = None
        self._processor = None
        self._model = None
        self._model_error: str | None = None
        self._model_loaded = False

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

        layout = _heuristic_layout(image_bytes, image)
        payload: dict[str, Any] = {"text": json.dumps(layout), "layout": layout, "backend": self._backend}
        caption = self._caption_from_model(image)
        if caption:
            payload["caption"] = caption
            payload["text_plain"] = caption
        if self._model_path:
            payload["model_id"] = str(self._model_path)
        if self._model_error:
            payload["model_error"] = self._model_error
        return payload

    def _caption_from_model(self, image: "Image.Image") -> str:
        self._load_model()
        if self._pipeline is not None:
            try:
                result = self._pipeline(image, max_new_tokens=self._max_new_tokens)
            except Exception as exc:
                self._model_error = f"vlm_pipeline_error:{exc}"
                return ""
            if isinstance(result, list) and result:
                text = result[0].get("generated_text") or result[0].get("text")
                return str(text or "").strip()
            return ""
        if self._model is None or self._processor is None:
            return ""
        try:
            inputs = self._processor(images=image, text=self._prompt, return_tensors="pt")
            device = next(self._model.parameters()).device
            inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}
            generated = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
            )
            text = self._processor.batch_decode(generated, skip_special_tokens=True)
            return str(text[0]).strip() if text else ""
        except Exception as exc:
            self._model_error = f"vlm_generate_failed:{exc}"
            return ""

    def _load_model(self) -> None:
        if self._model_loaded:
            return
        self._model_loaded = True
        if not self._model_path:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        try:
            from transformers import pipeline
        except Exception as exc:
            self._model_error = f"vlm_transformers_missing:{exc}"
            return
        try:
            self._pipeline = pipeline("image-to-text", model=self._model_path, local_files_only=True)
            self._backend = "transformers.pipeline"
            return
        except Exception:
            self._pipeline = None
        try:
            from transformers import AutoProcessor, AutoModelForVision2Seq
        except Exception:
            AutoProcessor = None
            AutoModelForVision2Seq = None
        try:
            from transformers import AutoModelForCausalLM
        except Exception:
            AutoModelForCausalLM = None
        try:
            import torch
        except Exception as exc:
            self._model_error = f"vlm_torch_missing:{exc}"
            return
        processor = None
        if AutoProcessor is not None:
            try:
                processor = AutoProcessor.from_pretrained(self._model_path, local_files_only=True)
            except Exception:
                processor = None
        model = None
        if AutoModelForVision2Seq is not None:
            try:
                model = AutoModelForVision2Seq.from_pretrained(self._model_path, local_files_only=True)
            except Exception:
                model = None
        if model is None and AutoModelForCausalLM is not None:
            try:
                model = AutoModelForCausalLM.from_pretrained(self._model_path, local_files_only=True)
            except Exception:
                model = None
        if model is None or processor is None:
            self._model_error = "vlm_model_load_failed"
            return
        try:
            model.eval()
        except Exception:
            pass
        try:
            torch.manual_seed(0)
            torch.set_grad_enabled(False)
            if hasattr(torch, "use_deterministic_algorithms"):
                torch.use_deterministic_algorithms(True)
        except Exception:
            pass
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        try:
            model.to(device)
        except Exception:
            pass
        self._processor = processor
        self._model = model
        self._backend = "transformers.vision2seq"


def create_plugin(plugin_id: str, context: PluginContext) -> VLMStub:
    return VLMStub(plugin_id, context)


def _heuristic_layout(image_bytes: bytes, image: "Image.Image") -> dict[str, Any]:
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
    return {"elements": elements, "edges": []}


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
