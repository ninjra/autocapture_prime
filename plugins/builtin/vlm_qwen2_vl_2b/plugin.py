"""Two-pass local Qwen2-VL extractor (thumbnail ROI + hi-res ROI merge)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

from autocapture.models.bundles import BundleInfo, select_bundle
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", flags=re.IGNORECASE | re.DOTALL)

_THUMB_PROMPT = (
    "You are a strict UI parser.\n"
    "Return JSON only.\n"
    "Schema:\n"
    '{"rois":[{"id":"string","kind":"window|pane|tabstrip|console|calendar|chat|email|browser|other",'
    '"label":"string","bbox_norm":[x1,y1,x2,y2],"priority":0.0}],'
    '"windows":[{"label":"string","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],'
    '"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}]}\n'
    "Rules: normalized coords in [0,1], x1<x2, y1<y2; include likely top-level windows/panes.\n"
    "Do not add prose."
)

_ROI_PROMPT = (
    "You are a strict UI parser for one cropped region.\n"
    "Return JSON only.\n"
    "Schema:\n"
    '{"elements":[{"type":"window|pane|tab|button|row|cell|text|icon|list_item|other",'
    '"label":"string","bbox_norm":[x1,y1,x2,y2],"state":{"focused":false,"selected":false},'
    '"attrs":{"app":"string","context":"host|vdi|unknown"}}],'
    '"facts":[{"key":"string","value":"string","confidence":0.0}],'
    '"windows":[{"label":"string","app":"string","context":"host|vdi|unknown",'
    '"bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}]}\n'
    "Rules: normalized coords in [0,1], x1<x2, y1<y2; no markdown, no prose."
)


@dataclass(frozen=True)
class _Roi:
    roi_id: str
    kind: str
    label: str
    priority_bp: int
    bbox_px: tuple[int, int, int, int]


class Qwen2VL2B(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        self._model_path = self._resolve_model_path(models_cfg)
        self._thumb_width = int(models_cfg.get("thumb_width") or 1920)
        self._thumb_height = int(models_cfg.get("thumb_height") or 540)
        self._max_rois = max(1, int(models_cfg.get("max_rois") or 5))
        self._roi_max_side = max(512, int(models_cfg.get("roi_max_side") or 2048))
        self._thumb_tokens = max(64, int(models_cfg.get("thumb_max_new_tokens") or 220))
        self._roi_tokens = max(64, int(models_cfg.get("roi_max_new_tokens") or 220))
        self._backend = "unavailable"
        self._bundle: BundleInfo | None = None
        self._model_error = ""
        self._processor = None
        self._model = None
        self._torch = None
        self._model_loaded = False

    def capabilities(self) -> dict[str, Any]:
        return {"vision.extractor": self}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backend": "unavailable",
            "text": "",
            "layout": {"elements": [], "edges": []},
            "ui_state": {},
        }
        if not image_bytes or not _PIL_AVAILABLE:
            return payload
        try:
            image = Image.open(_as_bytes_io(image_bytes)).convert("RGB")
        except Exception as exc:
            payload["model_error"] = f"image_decode_failed:{type(exc).__name__}:{exc}"
            return payload

        self._ensure_model()
        if self._model is None or self._processor is None or self._torch is None:
            payload["model_error"] = self._model_error or "vlm_model_unavailable"
            return payload

        thumb = image.resize((self._thumb_width, self._thumb_height))
        thumb_raw = self._run_prompt_json(thumb, _THUMB_PROMPT, max_new_tokens=self._thumb_tokens)
        rois = self._collect_rois(thumb_raw, width=image.width, height=image.height)

        windows_seed = self._parse_windows(thumb_raw, width=image.width, height=image.height)
        facts: list[dict[str, Any]] = []
        windows: list[dict[str, Any]] = list(windows_seed)
        elements: list[dict[str, Any]] = []
        roi_reports: list[dict[str, Any]] = []

        for roi in rois:
            crop = image.crop(roi.bbox_px)
            if max(crop.width, crop.height) > self._roi_max_side:
                scale = float(self._roi_max_side) / float(max(crop.width, crop.height))
                nw = max(1, int(round(float(crop.width) * scale)))
                nh = max(1, int(round(float(crop.height) * scale)))
                crop = crop.resize((nw, nh))
            roi_raw = self._run_prompt_json(crop, _ROI_PROMPT, max_new_tokens=self._roi_tokens)
            roi_reports.append(
                {
                    "id": roi.roi_id,
                    "kind": roi.kind,
                    "label": roi.label,
                    "priority_bp": int(roi.priority_bp),
                    "bbox_px": list(roi.bbox_px),
                    "raw_ok": bool(isinstance(roi_raw, dict)),
                }
            )
            if not isinstance(roi_raw, dict):
                continue
            for element in self._parse_elements(roi_raw, roi):
                elements.append(element)
            for item in self._parse_windows(roi_raw, width=image.width, height=image.height, parent_roi=roi):
                windows.append(item)
            for fact in self._parse_facts(roi_raw, roi):
                facts.append(fact)

        merged_elements = _dedupe_elements(elements)
        merged_windows = _dedupe_windows(windows)
        merged_facts = _dedupe_facts(facts)
        layout_elements = _to_layout_elements(merged_elements, merged_windows)
        text = json.dumps({"elements": layout_elements}, sort_keys=True, separators=(",", ":"))
        ui_state = {
            "schema_version": 1,
            "image_size": [int(image.width), int(image.height)],
            "rois": [self._roi_to_dict(r) for r in rois],
            "windows": merged_windows,
            "facts": merged_facts,
            "roi_reports": roi_reports,
        }
        layout = {
            "elements": layout_elements,
            "edges": [],
            "state_id": "vlm",
            "source_backend": "transformers.qwen2vl_two_pass",
            "source_provider_id": self.plugin_id,
            "ui_state": ui_state,
        }
        payload.update(
            {
                "backend": "transformers.qwen2vl_two_pass",
                "model_id": str(self._model_path or ""),
                "layout": layout,
                "ui_state": ui_state,
                "text": text,
            }
        )
        if self._model_error:
            payload["model_error"] = self._model_error
        return payload

    def _resolve_model_path(self, models_cfg: dict[str, Any]) -> str:
        raw = str(models_cfg.get("vlm_path") or "").strip()
        if raw:
            return raw
        bundle = select_bundle("vlm")
        if bundle is not None:
            self._bundle = bundle
            candidate = str(bundle.config.get("model_path") or "").strip()
            if candidate:
                if os.path.isabs(candidate):
                    return candidate
                return str(Path(bundle.path) / candidate)
        default = Path("/mnt/d/autocapture/models/qwen2-vl-2b-instruct")
        return str(default)

    def _ensure_model(self) -> None:
        if self._model_loaded:
            return
        self._model_loaded = True
        if not self._model_path:
            self._model_error = "vlm_model_path_missing"
            return
        try:
            import torch
            from transformers import AutoProcessor
            try:
                from transformers import Qwen2VLForConditionalGeneration
            except Exception:
                from transformers.models.qwen2_vl.modeling_qwen2_vl import Qwen2VLForConditionalGeneration
        except Exception as exc:
            self._model_error = f"transformers_missing:{type(exc).__name__}:{exc}"
            return
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            model = None
            torch_dtype = getattr(torch, "float16", None) if bool(getattr(torch.cuda, "is_available", lambda: False)()) else "auto"
            try:
                model = Qwen2VLForConditionalGeneration.from_pretrained(
                    self._model_path,
                    local_files_only=True,
                    torch_dtype=torch_dtype,
                    device_map="auto",
                )
            except Exception:
                model = Qwen2VLForConditionalGeneration.from_pretrained(
                    self._model_path,
                    local_files_only=True,
                    torch_dtype=torch_dtype,
                )
            processor = AutoProcessor.from_pretrained(
                self._model_path,
                local_files_only=True,
            )
            model.eval()
            if bool(getattr(torch.cuda, "is_available", lambda: False)()):
                try:
                    model = model.to("cuda")
                except Exception:
                    pass
            try:
                torch.set_grad_enabled(False)
                torch.manual_seed(0)
                if hasattr(torch, "use_deterministic_algorithms"):
                    torch.use_deterministic_algorithms(True)
            except Exception:
                pass
            self._torch = torch
            self._model = model
            self._processor = processor
            self._backend = "transformers.qwen2vl_cpu_direct"
        except Exception as exc:
            self._model_error = f"model_load_failed:{type(exc).__name__}:{exc}"

    def _run_prompt_json(self, image: "Image.Image", prompt: str, *, max_new_tokens: int) -> dict[str, Any]:
        if self._model is None or self._processor is None or self._torch is None:
            return {}
        try:
            messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
            text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self._processor(text=[text], images=[image], return_tensors="pt")
            model_device = getattr(self._model, "device", None)
            if model_device is not None:
                try:
                    inputs = inputs.to(model_device)
                except Exception:
                    try:
                        moved: dict[str, Any] = {}
                        for key, value in dict(inputs).items():
                            if hasattr(value, "to"):
                                moved[key] = value.to(model_device)
                            else:
                                moved[key] = value
                        inputs = moved
                    except Exception:
                        pass
            with self._torch.no_grad():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                )
            prompt_len = int(inputs.input_ids.shape[1]) if hasattr(inputs, "input_ids") else 0
            trimmed: list[Any] = []
            for i in range(int(output_ids.shape[0])):
                trimmed.append(output_ids[i][prompt_len:])
            decoded = self._processor.batch_decode(
                trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            raw_text = str(decoded[0] if decoded else "").strip()
        except Exception as exc:
            self._model_error = f"inference_failed:{type(exc).__name__}:{exc}"
            return {}
        parsed = _extract_json(raw_text)
        if isinstance(parsed, dict):
            return parsed
        return {}

    def _collect_rois(self, raw: dict[str, Any], *, width: int, height: int) -> list[_Roi]:
        out: list[_Roi] = []
        out.append(_Roi("full", "window", "full_image", 10000, (0, 0, int(width), int(height))))
        rois = raw.get("rois", []) if isinstance(raw, dict) else []
        if isinstance(rois, list):
            for idx, item in enumerate(rois, start=1):
                if not isinstance(item, dict):
                    continue
                bbox = _norm_bbox_to_px(item.get("bbox_norm"), width=width, height=height)
                if bbox is None:
                    continue
                roi = _Roi(
                    roi_id=str(item.get("id") or f"roi_{idx}"),
                    kind=str(item.get("kind") or "other"),
                    label=str(item.get("label") or ""),
                    priority_bp=_to_bp(item.get("priority"), default_bp=6000),
                    bbox_px=bbox,
                )
                out.append(roi)
        out.sort(key=lambda r: (-int(r.priority_bp), r.roi_id))
        dedup: list[_Roi] = []
        for roi in out:
            keep = True
            for existing in dedup:
                if _iou(roi.bbox_px, existing.bbox_px) >= 0.85:
                    keep = False
                    break
            if keep:
                dedup.append(roi)
            if len(dedup) >= self._max_rois:
                break
        return dedup

    def _parse_elements(self, raw: dict[str, Any], roi: _Roi) -> list[dict[str, Any]]:
        elements_raw = raw.get("elements", [])
        if not isinstance(elements_raw, list):
            return []
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(elements_raw, start=1):
            if not isinstance(item, dict):
                continue
            bbox = _norm_bbox_to_px(item.get("bbox_norm"), width=_roi_w(roi), height=_roi_h(roi))
            if bbox is None:
                continue
            gx1 = roi.bbox_px[0] + bbox[0]
            gy1 = roi.bbox_px[1] + bbox[1]
            gx2 = roi.bbox_px[0] + bbox[2]
            gy2 = roi.bbox_px[1] + bbox[3]
            label = _clean_text(item.get("label"))
            if not label:
                continue
            state = item.get("state")
            attrs = item.get("attrs")
            out.append(
                {
                    "id": f"{roi.roi_id}:el:{idx}",
                    "type": _clean_text(item.get("type")) or "other",
                    "bbox": [int(gx1), int(gy1), int(gx2), int(gy2)],
                    "label": label,
                    "interactable": bool(_is_interactable_type(str(item.get("type") or ""))),
                    "state": state if isinstance(state, dict) else {},
                    "attrs": attrs if isinstance(attrs, dict) else {},
                    "source_roi": roi.roi_id,
                }
            )
        return out

    def _parse_windows(
        self,
        raw: dict[str, Any],
        *,
        width: int,
        height: int,
        parent_roi: _Roi | None = None,
    ) -> list[dict[str, Any]]:
        windows_raw = raw.get("windows", []) if isinstance(raw.get("windows"), list) else []
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(windows_raw, start=1):
            if not isinstance(item, dict):
                continue
            bbox_norm = item.get("bbox_norm")
            bbox: tuple[int, int, int, int] | None = None
            if parent_roi is None:
                bbox = _norm_bbox_to_px(bbox_norm, width=width, height=height)
            else:
                local = _norm_bbox_to_px(bbox_norm, width=_roi_w(parent_roi), height=_roi_h(parent_roi))
                if local is not None:
                    bbox = (
                        int(parent_roi.bbox_px[0] + local[0]),
                        int(parent_roi.bbox_px[1] + local[1]),
                        int(parent_roi.bbox_px[0] + local[2]),
                        int(parent_roi.bbox_px[1] + local[3]),
                    )
            if bbox is None:
                continue
            out.append(
                {
                    "window_id": f"{parent_roi.roi_id if parent_roi else 'thumb'}:w:{idx}",
                    "label": _clean_text(item.get("label")),
                    "app": _clean_text(item.get("app")) or _clean_text(item.get("label")),
                    "context": _enum_or_default(item.get("context"), {"host", "vdi", "unknown"}, "unknown"),
                    "visibility": _enum_or_default(
                        item.get("visibility"),
                        {"fully_visible", "partially_occluded", "unknown"},
                        "unknown",
                    ),
                    "z_hint_bp": _to_bp(item.get("z_hint"), default_bp=5000),
                    "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                    "source_roi": parent_roi.roi_id if parent_roi else "thumbnail",
                }
            )
        return out

    def _parse_facts(self, raw: dict[str, Any], roi: _Roi) -> list[dict[str, Any]]:
        facts_raw = raw.get("facts", [])
        if not isinstance(facts_raw, list):
            return []
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(facts_raw, start=1):
            if not isinstance(item, dict):
                continue
            key = _clean_text(item.get("key"))
            value = _clean_text(item.get("value"))
            if not key or not value:
                continue
            out.append(
                {
                    "fact_id": f"{roi.roi_id}:f:{idx}",
                    "key": key,
                    "value": value,
                    "confidence_bp": _to_bp(item.get("confidence"), default_bp=7000),
                    "source_roi": roi.roi_id,
                }
            )
        return out

    @staticmethod
    def _roi_to_dict(roi: _Roi) -> dict[str, Any]:
        return {
            "id": roi.roi_id,
            "kind": roi.kind,
            "label": roi.label,
            "priority_bp": int(roi.priority_bp),
            "bbox_px": [int(roi.bbox_px[0]), int(roi.bbox_px[1]), int(roi.bbox_px[2]), int(roi.bbox_px[3])],
        }


def create_plugin(plugin_id: str, context: PluginContext) -> Qwen2VL2B:
    return Qwen2VL2B(plugin_id, context)


def _as_bytes_io(blob: bytes):  # pragma: no cover - thin helper
    from io import BytesIO

    return BytesIO(blob)


def _extract_assistant_text(result: Any) -> str:
    if not isinstance(result, list) or not result:
        return ""
    first = result[0] if isinstance(result[0], dict) else {}
    generated = first.get("generated_text")
    if isinstance(generated, str):
        return generated.strip()
    if isinstance(generated, list):
        for entry in reversed(generated):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").strip() != "assistant":
                continue
            content = entry.get("content")
            if isinstance(content, str):
                return content.strip()
    return ""


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    match = _JSON_BLOCK_RE.search(raw)
    candidates: list[str] = []
    if match:
        candidates.append(match.group(1))
    candidates.append(raw)
    for item in candidates:
        try:
            parsed = json.loads(item)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        chunk = raw[start : end + 1]
        try:
            parsed = json.loads(chunk)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _enum_or_default(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().casefold()
    return text if text in allowed else default


def _to_bp(value: Any, *, default_bp: int) -> int:
    try:
        num = float(value)
    except Exception:
        return int(default_bp)
    if num <= 1.0:
        num *= 10000.0
    return int(max(0.0, min(10000.0, num)))


def _norm_bbox_to_px(raw: Any, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
    except Exception:
        return None
    if x1 < 0.0 or y1 < 0.0 or x2 > 1.0 or y2 > 1.0:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    px1 = int(max(0, min(width, round(x1 * float(width)))))
    py1 = int(max(0, min(height, round(y1 * float(height)))))
    px2 = int(max(0, min(width, round(x2 * float(width)))))
    py2 = int(max(0, min(height, round(y2 * float(height)))))
    if px2 <= px1 or py2 <= py1:
        return None
    return (px1, py1, px2, py2)


def _roi_w(roi: _Roi) -> int:
    return int(max(1, roi.bbox_px[2] - roi.bbox_px[0]))


def _roi_h(roi: _Roi) -> int:
    return int(max(1, roi.bbox_px[3] - roi.bbox_px[1]))


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = float(iw * ih)
    if inter <= 0.0:
        return 0.0
    area_a = float(max(1, (ax2 - ax1) * (ay2 - ay1)))
    area_b = float(max(1, (bx2 - bx1) * (by2 - by1)))
    union = max(1.0, area_a + area_b - inter)
    return inter / union


def _is_interactable_type(kind: str) -> bool:
    low = str(kind or "").casefold()
    return low in {"button", "tab", "list_item", "row", "cell", "icon"}


def _dedupe_elements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        except Exception:
            continue
        label = _clean_text(item.get("label"))
        kind = _clean_text(item.get("type"))
        duplicate = False
        for existing in out:
            eb = existing.get("bbox")
            if not isinstance(eb, list) or len(eb) != 4:
                continue
            eb_tuple = (int(eb[0]), int(eb[1]), int(eb[2]), int(eb[3]))
            if _iou(bbox, eb_tuple) >= 0.92 and label.casefold() == _clean_text(existing.get("label")).casefold():
                duplicate = True
                break
        if duplicate:
            continue
        out.append(
            {
                "id": str(item.get("id") or ""),
                "type": kind or "other",
                "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                "label": label,
                "interactable": bool(item.get("interactable", False)),
                "state": item.get("state", {}) if isinstance(item.get("state"), dict) else {},
                "attrs": item.get("attrs", {}) if isinstance(item.get("attrs"), dict) else {},
                "source_roi": str(item.get("source_roi") or ""),
            }
        )
    out.sort(key=lambda e: (int(e["bbox"][1]), int(e["bbox"][0]), str(e.get("label") or "")))
    return out[:800]


def _dedupe_windows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        except Exception:
            continue
        app = _clean_text(item.get("app"))
        context = _enum_or_default(item.get("context"), {"host", "vdi", "unknown"}, "unknown")
        duplicate = False
        for existing in out:
            eb = existing.get("bbox")
            if not isinstance(eb, list) or len(eb) != 4:
                continue
            eb_tuple = (int(eb[0]), int(eb[1]), int(eb[2]), int(eb[3]))
            if _iou(bbox, eb_tuple) >= 0.86 and app.casefold() == _clean_text(existing.get("app")).casefold():
                duplicate = True
                break
        if duplicate:
            continue
        out.append(
            {
                "window_id": str(item.get("window_id") or ""),
                "label": _clean_text(item.get("label")),
                "app": app,
                "context": context,
                "visibility": _enum_or_default(
                    item.get("visibility"),
                    {"fully_visible", "partially_occluded", "unknown"},
                    "unknown",
                ),
                "z_hint_bp": int(item.get("z_hint_bp") or 5000),
                "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                "source_roi": str(item.get("source_roi") or ""),
            }
        )
    out.sort(key=lambda w: (-int(w.get("z_hint_bp") or 0), str(w.get("app") or "")))
    return out[:80]


def _dedupe_facts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = _clean_text(item.get("key"))
        value = _clean_text(item.get("value"))
        if not key or not value:
            continue
        fp = (key.casefold(), value.casefold())
        if fp in seen:
            continue
        seen.add(fp)
        out.append(
            {
                "fact_id": str(item.get("fact_id") or ""),
                "key": key,
                "value": value,
                "confidence_bp": int(item.get("confidence_bp") or 7000),
                "source_roi": str(item.get("source_roi") or ""),
            }
        )
    out.sort(key=lambda f: (-int(f.get("confidence_bp") or 0), str(f.get("key") or ""), str(f.get("value") or "")))
    return out[:400]


def _build_text(windows: list[dict[str, Any]], facts: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"windows.count={len(windows)}")
    for idx, window in enumerate(windows[:24], start=1):
        app = _clean_text(window.get("app"))
        context = _clean_text(window.get("context"))
        visibility = _clean_text(window.get("visibility"))
        lines.append(f"window.{idx}.app={app}")
        lines.append(f"window.{idx}.context={context}")
        lines.append(f"window.{idx}.visibility={visibility}")
    for idx, fact in enumerate(facts[:240], start=1):
        key = _clean_text(fact.get("key"))
        value = _clean_text(fact.get("value"))
        lines.append(f"fact.{idx}.{key}={value}")
    return "\n".join(lines)


def _to_layout_elements(items: list[dict[str, Any]], windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = [int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])]
        except Exception:
            continue
        out.append(
            {
                "type": _clean_text(item.get("type")) or "other",
                "bbox": bbox,
                "text": _clean_text(item.get("label")),
                "interactable": bool(item.get("interactable", False)),
                "state": item.get("state", {}) if isinstance(item.get("state"), dict) else {},
                "children": [],
            }
        )
    for window in windows:
        bbox_raw = window.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = [int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])]
        except Exception:
            continue
        label = _clean_text(window.get("label")) or _clean_text(window.get("app"))
        out.append(
            {
                "type": "window",
                "bbox": bbox,
                "text": label,
                "interactable": False,
                "state": {},
                "children": [],
            }
        )
    dedup: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, int, int, int], str]] = set()
    for item in out:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        fp = (
            _clean_text(item.get("type")) or "other",
            (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])),
            _clean_text(item.get("text")),
        )
        if fp in seen:
            continue
        seen.add(fp)
        dedup.append(item)
    return dedup
