"""Localhost-only VLM via an OpenAI-compatible server (for example vLLM)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from autocapture_nx.inference.openai_compat import OpenAICompatClient, image_bytes_to_data_url
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

try:  # pragma: no cover - optional dependency guard
    from PIL import Image

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


DEFAULT_LAYOUT_PROMPT = (
    "Return STRICT JSON only with schema "
    '{"elements":[{"type":"window","bbox":[x1,y1,x2,y2],"text":"visible text",'
    '"interactable":true,"state":{"enabled":true,"selected":false,"focused":false,"expanded":false},'
    '"children":[...]}]}. '
    "Use absolute pixel coordinates relative to the provided image. "
    "Detect visible UI structure and preserve nesting. "
    "Do not emit placeholder literals like 'string' or enum lists; fill values from the actual image. "
    "Do not include markdown, prose, or keys outside this schema."
)

DEFAULT_THUMB_PROMPT = (
    "Detect UI regions in this screenshot and return JSON only.\n"
    "Schema: "
    '{"rois":[{"id":"r1","kind":"window|pane|tabstrip|console|calendar|chat|email|browser|other","label":"text","bbox_norm":[x1,y1,x2,y2],"priority":0.0}],'
    '"windows":[{"label":"text","app":"text","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}]}. '
    "Use normalized bbox values in [0,1], include diverse ROIs across the full image, and return only valid JSON."
)

DEFAULT_ROI_PROMPT = (
    "Parse this cropped UI region and return JSON only.\n"
    "Schema: "
    '{"elements":[{"type":"window|pane|button|row|cell|text|other","label":"text","bbox_norm":[x1,y1,x2,y2]}],'
    '"windows":[{"label":"text","app":"text","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}],'
    '"facts":[{"key":"adv.* key","value":"visible text value","confidence":0.0}]}. '
    "Use canonical fact keys when visible (adv.window.*, adv.focus.*, adv.incident.*, adv.activity.*, adv.details.*, "
    "adv.calendar.*, adv.slack.*, adv.dev.*, adv.console.*, adv.browser.*). "
    "Use only visible evidence, valid normalized bboxes, and return valid JSON only."
)


@dataclass(frozen=True)
class _Roi:
    roi_id: str
    kind: str
    label: str
    priority_bp: int
    bbox_px: tuple[int, int, int, int]


class VllmVLM(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._base_url_policy_error = ""
        try:
            self._base_url = enforce_external_vllm_base_url(cfg.get("base_url"))
        except Exception as exc:
            self._base_url = EXTERNAL_VLLM_BASE_URL
            self._base_url_policy_error = f"invalid_vllm_base_url:{type(exc).__name__}:{exc}"
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 30.0)
        self._prompt = str(cfg.get("prompt") or DEFAULT_LAYOUT_PROMPT).strip()
        self._max_tokens = int(cfg.get("max_tokens") or 256)
        self._temperature = float(cfg.get("temperature") if "temperature" in cfg else 0.0)
        self._top_p = float(cfg.get("top_p") if "top_p" in cfg else 1.0)
        self._n = max(1, int(cfg.get("n") if "n" in cfg else 1))
        seed_raw = cfg.get("seed")
        self._seed: int | None = None
        if seed_raw is not None and str(seed_raw).strip() != "":
            try:
                self._seed = int(seed_raw)
            except Exception:
                self._seed = None
        self._two_pass_enabled = bool(cfg.get("two_pass_enabled", True))
        self._thumb_prompt = str(cfg.get("thumb_prompt") or DEFAULT_THUMB_PROMPT).strip()
        self._roi_prompt = str(cfg.get("roi_prompt") or DEFAULT_ROI_PROMPT).strip()
        self._thumb_max_px = max(512, int(cfg.get("thumb_max_px") or 960))
        self._max_rois = max(1, int(cfg.get("max_rois") or 8))
        self._roi_max_side = max(512, int(cfg.get("roi_max_side") or 2048))
        self._thumb_max_tokens = max(128, int(cfg.get("thumb_max_tokens") or 768))
        self._roi_max_tokens = max(128, int(cfg.get("roi_max_tokens") or 1536))
        self._max_retries = max(1, min(5, int(cfg.get("max_retries") or 3)))
        self._client: OpenAICompatClient | None = None
        self._last_chat_error = ""
        self._model_validated = False

    def capabilities(self) -> dict[str, Any]:
        return {"vision.extractor": self}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        payload: dict[str, Any] = {"layout": {"elements": [], "edges": []}, "backend": "unavailable", "text": ""}
        if not image_bytes:
            return payload
        client = self._ensure_client(payload)
        if client is None:
            return payload
        self._resolve_model(client)
        if not self._model:
            payload["model_error"] = "vlm_model_missing"
            return payload
        if self._two_pass_enabled and _PIL_AVAILABLE:
            two_pass = self._run_two_pass(client, image_bytes)
            layout = two_pass.get("layout", {}) if isinstance(two_pass.get("layout", {}), dict) else {}
            elements = layout.get("elements", []) if isinstance(layout.get("elements", []), list) else []
            ui_state = layout.get("ui_state", {}) if isinstance(layout.get("ui_state", {}), dict) else {}
            has_structured = bool(
                (isinstance(ui_state.get("windows"), list) and len(ui_state.get("windows", [])) > 0)
                or (isinstance(ui_state.get("facts"), list) and len(ui_state.get("facts", [])) > 0)
            )
            if _valid_layout(layout) and (len(elements) >= 2 or has_structured):
                payload.update(two_pass)
                return payload
        # Fallback to single-pass layout extraction.
        single = self._run_single_pass(client, image_bytes)
        payload.update(single)
        return payload

    def _ensure_client(self, payload: dict[str, Any]) -> OpenAICompatClient | None:
        if self._client is not None:
            return self._client
        if self._base_url_policy_error:
            payload["model_error"] = self._base_url_policy_error
            return None
        try:
            self._client = OpenAICompatClient(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout_s=self._timeout_s,
            )
        except Exception as exc:
            payload["model_error"] = f"client_init_failed:{type(exc).__name__}:{exc}"
            self._client = None
        return self._client

    def _run_single_pass(self, client: OpenAICompatClient, image_bytes: bytes) -> dict[str, Any]:
        out: dict[str, Any] = {"layout": {"elements": [], "edges": []}, "backend": "unavailable", "text": ""}
        content = self._chat_image(client, image_bytes, self._prompt, max_tokens=self._max_tokens)
        if not content:
            detail = str(self._last_chat_error or "").strip()
            out["model_error"] = f"vlm_empty_response:{detail}" if detail else "vlm_empty_response"
            return out
        layout = _extract_layout_from_text(content)
        if _valid_layout(layout):
            layout = dict(layout)
            layout.setdefault("edges", [])
            layout["state_id"] = "vlm"
            source_backend = str(layout.get("source_backend") or "openai_compat_layout").strip() or "openai_compat_layout"
            layout["source_backend"] = source_backend
            layout["source_provider_id"] = self.plugin_id
            out["backend"] = source_backend
            out["layout"] = layout
            out["text"] = json.dumps(layout, sort_keys=True, separators=(",", ":"))
            out["model_id"] = self._model
            return out
        out["backend"] = "openai_compat_unparsed"
        out["text_plain"] = content
        out["model_error"] = "vlm_layout_parse_failed"
        return out

    def _run_two_pass(self, client: OpenAICompatClient, image_bytes: bytes) -> dict[str, Any]:
        out: dict[str, Any] = {"layout": {"elements": [], "edges": []}, "backend": "unavailable", "text": ""}
        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")  # type: ignore[arg-type]
        except Exception as exc:
            out["model_error"] = f"image_decode_failed:{type(exc).__name__}:{exc}"
            return out

        thumb = _make_thumbnail(image, max_width=self._thumb_max_px)
        thumb_bytes = _encode_png(thumb)
        thumb_content = self._chat_image(client, thumb_bytes, self._thumb_prompt, max_tokens=self._thumb_max_tokens)
        if not thumb_content:
            detail = str(self._last_chat_error or "").strip()
            out["model_error"] = f"vlm_two_pass_thumb_empty:{detail}" if detail else "vlm_two_pass_thumb_empty"
            return out
        thumb_json = _extract_layout_from_text(thumb_content)

        rois = _collect_rois(thumb_json, width=int(image.width), height=int(image.height), max_rois=self._max_rois)
        windows = _parse_windows(thumb_json, width=int(image.width), height=int(image.height), parent_roi=None)
        layout_elements: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        roi_reports: list[dict[str, Any]] = []

        for roi in rois:
            crop = image.crop(roi.bbox_px)
            if max(crop.width, crop.height) > self._roi_max_side:
                scale = float(self._roi_max_side) / float(max(crop.width, crop.height))
                crop = crop.resize((max(1, int(round(crop.width * scale))), max(1, int(round(crop.height * scale)))))
            crop_bytes = _encode_png(crop)
            roi_content = self._chat_image(client, crop_bytes, self._roi_prompt, max_tokens=self._roi_max_tokens)
            roi_json = _extract_layout_from_text(roi_content)
            roi_reports.append(
                {
                    "id": roi.roi_id,
                    "kind": roi.kind,
                    "label": roi.label,
                    "priority_bp": int(roi.priority_bp),
                    "bbox_px": list(roi.bbox_px),
                    "raw_ok": isinstance(roi_json, dict),
                }
            )
            if not isinstance(roi_json, dict):
                continue
            layout_elements.extend(_parse_elements(roi_json, parent_roi=roi))
            windows.extend(_parse_windows(roi_json, width=int(image.width), height=int(image.height), parent_roi=roi))
            facts.extend(_parse_facts(roi_json, parent_roi=roi))

        # Include window-level elements for better observation graph coverage.
        for win in _dedupe_windows(windows):
            layout_elements.append(
                {
                    "type": "window",
                    "bbox": list(win["bbox"]),
                    "text": str(win.get("label") or win.get("app") or "").strip(),
                    "interactable": False,
                    "state": {},
                    "children": [],
                }
            )
        layout_elements = _dedupe_elements(layout_elements)
        ui_state = {
            "schema_version": 1,
            "image_size": [int(image.width), int(image.height)],
            "rois": [_roi_to_dict(item) for item in rois],
            "windows": _dedupe_windows(windows),
            "facts": _dedupe_facts(facts),
            "roi_reports": roi_reports,
        }
        layout = {
            "elements": layout_elements,
            "edges": [],
            "state_id": "vlm",
            "source_backend": "openai_compat_two_pass",
            "source_provider_id": self.plugin_id,
            "ui_state": ui_state,
        }
        out["backend"] = "openai_compat_two_pass"
        out["layout"] = layout
        out["text"] = json.dumps(
            {
                "elements": layout_elements,
                "windows": ui_state.get("windows", []),
                "facts": ui_state.get("facts", []),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        out["model_id"] = self._model
        out["ui_state"] = ui_state
        if not layout_elements:
            detail = str(self._last_chat_error or "").strip()
            out["model_error"] = f"vlm_two_pass_empty:{detail}" if detail else "vlm_two_pass_empty"
        return out

    def _chat_image(self, client: OpenAICompatClient, image_bytes: bytes, prompt: str, *, max_tokens: int) -> str:
        if not self._model:
            self._last_chat_error = "model_missing"
            return ""
        self._last_chat_error = ""
        current = bytes(image_bytes or b"")
        for _attempt in range(int(self._max_retries)):
            req: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_bytes_to_data_url(current, content_type="image/png")}},
                        ],
                    }
                ],
                "temperature": float(self._temperature),
                "top_p": float(self._top_p),
                "n": int(self._n),
                "max_tokens": int(max_tokens),
            }
            if self._seed is not None:
                req["seed"] = int(self._seed)
            try:
                resp = client.chat_completions(req)
            except Exception as exc:
                msg = str(exc or "").casefold()
                if "http_error:500" in msg or "internal server error" in msg:
                    self._last_chat_error = str(exc or "chat_exception").strip()[:240]
                    return ""
                if _is_model_not_found_error(msg):
                    previous = str(self._model or "").strip()
                    self._model_validated = False
                    self._resolve_model(client)
                    if self._model and str(self._model).strip() and str(self._model).strip() != previous:
                        self._last_chat_error = f"model_fallback:{previous}->{self._model}"
                        continue
                if _is_context_limit_error(msg):
                    downsized = _downscale_png_bytes(current)
                    if downsized and len(downsized) < len(current):
                        current = downsized
                        self._last_chat_error = "context_limit_downscaled_retry"
                        continue
                self._last_chat_error = str(exc or "chat_exception").strip()[:240]
                return ""
            choices = resp.get("choices", [])
            if not isinstance(choices, list) or not choices:
                self._last_chat_error = "empty_choices"
                return ""
            msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = str(msg.get("content") or "").strip()
            if content:
                self._last_chat_error = ""
                return content
            downsized = _downscale_png_bytes(current)
            if downsized and len(downsized) < len(current):
                current = downsized
                self._last_chat_error = "empty_content_downscaled_retry"
                continue
            self._last_chat_error = "empty_content"
            return ""
        self._last_chat_error = "max_retries_exhausted"
        return ""

    @staticmethod
    def _discover_model(client: OpenAICompatClient) -> str | None:
        ids = VllmVLM._discover_model_ids(client)
        return ids[0] if ids else None

    @staticmethod
    def _discover_model_ids(client: OpenAICompatClient) -> list[str]:
        try:
            models = client.list_models()
        except Exception:
            return []
        data = models.get("data", []) if isinstance(models, dict) else []
        if not isinstance(data, list):
            return []
        out: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                out.append(model_id)
        return out

    def _resolve_model(self, client: OpenAICompatClient) -> str | None:
        if self._model and self._model_validated:
            return self._model
        model_ids = self._discover_model_ids(client)
        if not model_ids:
            return self._model
        if self._model and self._model in model_ids:
            self._model_validated = True
            return self._model
        self._model = model_ids[0]
        self._model_validated = True
        return self._model


def create_plugin(plugin_id: str, context: PluginContext) -> VllmVLM:
    return VllmVLM(plugin_id, context)


def _extract_layout_from_text(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    candidates = [match.group(1)] if match else []
    candidates.append(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blob = text[start : end + 1]
        try:
            parsed = json.loads(blob)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    recovered = _recover_layout_from_partial_json(text)
    if recovered:
        return recovered
    return {}


_PARTIAL_ELEMENT_RE = re.compile(
    r'"type"\s*:\s*"(?P<type>[^"]+)"(?P<mid>.{0,640}?)"bbox"\s*:\s*\[(?P<bbox>[^\]]+)\](?P<tail>.{0,640})',
    flags=re.IGNORECASE | re.DOTALL,
)


def _recover_layout_from_partial_json(text: str) -> dict[str, Any]:
    blob = str(text or "")
    if not blob:
        return {}
    elements: list[dict[str, Any]] = []
    for match in _PARTIAL_ELEMENT_RE.finditer(blob):
        element_type = _clean_text(match.group("type")).casefold() or "other"
        if element_type in {"", "null"}:
            continue
        bbox_values = _parse_bbox_values(match.group("bbox") or "")
        if bbox_values is None:
            continue
        snippet = f"{match.group('mid') or ''}{match.group('tail') or ''}"
        label = ""
        m_text = re.search(r'"text"\s*:\s*"([^"]{1,180})"', snippet, flags=re.IGNORECASE)
        if m_text:
            label = _clean_text(m_text.group(1))
        if not label:
            m_label = re.search(r'"label"\s*:\s*"([^"]{1,180})"', snippet, flags=re.IGNORECASE)
            if m_label:
                label = _clean_text(m_label.group(1))
        elements.append(
            {
                "type": element_type,
                "bbox": [float(bbox_values[0]), float(bbox_values[1]), float(bbox_values[2]), float(bbox_values[3])],
                "text": label,
                "interactable": bool(element_type in {"button", "textbox", "checkbox", "radio", "dropdown", "tab", "menu", "icon"}),
                "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                "children": [],
            }
        )
        if len(elements) >= 64:
            break
    rois: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []

    for m in re.finditer(
        r'"id"\s*:\s*"(?P<id>[^"]+)"(?P<mid>.{0,300}?)"kind"\s*:\s*"(?P<kind>[^"]+)"(?P<tail>.{0,500}?)"bbox_norm"\s*:\s*\[(?P<bbox>[^\]]+)\]',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        bbox_values = _parse_bbox_values(m.group("bbox") or "")
        if bbox_values is None:
            continue
        label_match = re.search(r'"label"\s*:\s*"([^"]{1,120})"', f"{m.group('mid')}{m.group('tail')}", flags=re.IGNORECASE)
        pri_match = re.search(r'"priority"\s*:\s*(-?\d+(?:\.\d+)?)', f"{m.group('mid')}{m.group('tail')}", flags=re.IGNORECASE)
        rois.append(
            {
                "id": _clean_text(m.group("id")),
                "kind": _clean_text(m.group("kind")),
                "label": _clean_text(label_match.group(1) if label_match else ""),
                "bbox_norm": [bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3]],
                "priority": float(pri_match.group(1)) if pri_match else 0.0,
            }
        )
        if len(rois) >= 32:
            break

    for m in re.finditer(
        r'"label"\s*:\s*"(?P<label>[^"]{1,160})"(?P<mid>.{0,500}?)"app"\s*:\s*"(?P<app>[^"]{1,160})"(?P<tail>.{0,500}?)"bbox_norm"\s*:\s*\[(?P<bbox>[^\]]+)\]',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        bbox_values = _parse_bbox_values(m.group("bbox") or "")
        if bbox_values is None:
            continue
        side = f"{m.group('mid')}{m.group('tail')}"
        ctx = re.search(r'"context"\s*:\s*"([^"]+)"', side, flags=re.IGNORECASE)
        vis = re.search(r'"visibility"\s*:\s*"([^"]+)"', side, flags=re.IGNORECASE)
        z = re.search(r'"z_hint"\s*:\s*(-?\d+(?:\.\d+)?)', side, flags=re.IGNORECASE)
        windows.append(
            {
                "label": _clean_text(m.group("label")),
                "app": _clean_text(m.group("app")),
                "context": _clean_text(ctx.group(1) if ctx else "unknown"),
                "bbox_norm": [bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3]],
                "visibility": _clean_text(vis.group(1) if vis else "unknown"),
                "z_hint": float(z.group(1)) if z else 0.0,
            }
        )
        if len(windows) >= 32:
            break

    for m in re.finditer(
        r'"key"\s*:\s*"(?P<key>[^"]{1,180})"(?P<mid>.{0,300}?)"value"\s*:\s*"(?P<value>[^"]{1,400})"(?P<tail>.{0,120})',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        side = f"{m.group('mid')}{m.group('tail')}"
        conf = re.search(r'"confidence"\s*:\s*(-?\d+(?:\.\d+)?)', side, flags=re.IGNORECASE)
        facts.append(
            {
                "key": _clean_text(m.group("key")),
                "value": _clean_text(m.group("value")),
                "confidence": float(conf.group(1)) if conf else 0.7,
            }
        )
        if len(facts) >= 128:
            break

    if len(elements) < 1 and len(rois) < 1 and len(windows) < 1 and len(facts) < 1:
        return {}
    out: dict[str, Any] = {"edges": [], "state_id": "vlm", "source_backend": "openai_compat_text_recovered"}
    if elements:
        out["elements"] = elements
    if rois:
        out["rois"] = rois
    if windows:
        out["windows"] = windows
    if facts:
        out["facts"] = facts
    return out


def _parse_bbox_values(raw_bbox: str) -> tuple[float, float, float, float] | None:
    nums = re.findall(r"-?\d+(?:\.\d+)?", str(raw_bbox or ""))
    if len(nums) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3]))
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _valid_layout(layout: dict[str, Any]) -> bool:
    if not isinstance(layout, dict):
        return False
    elements = layout.get("elements")
    return isinstance(elements, list)


def _make_thumbnail(image: Any, *, max_width: int) -> Any:
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    if width <= 0 or height <= 0 or width <= max_width:
        return image
    scale = float(max_width) / float(width)
    return image.resize((int(max_width), max(1, int(round(height * scale)))))


def _is_context_limit_error(message: str) -> bool:
    text = str(message or "").casefold()
    return (
        "decoder prompt" in text
        or "maximum model length" in text
        or "max model length" in text
        or "context length" in text
        or "too many tokens" in text
    )


def _is_model_not_found_error(message: str) -> bool:
    text = str(message or "").casefold()
    return ("model" in text and "not found" in text) or ("model" in text and "does not exist" in text)


def _downscale_png_bytes(image_bytes: bytes) -> bytes | None:
    if not _PIL_AVAILABLE:
        return None
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")  # type: ignore[arg-type]
    except Exception:
        return None
    w = int(getattr(img, "width", 0) or 0)
    h = int(getattr(img, "height", 0) or 0)
    if w <= 0 or h <= 0:
        return None
    longest = max(w, h)
    if longest <= 512:
        return None
    scale = 0.75
    nw = max(256, int(round(float(w) * scale)))
    nh = max(256, int(round(float(h) * scale)))
    resized = img.resize((nw, nh))
    return _encode_png(resized)


def _encode_png(image: Any) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _roi_to_dict(roi: _Roi) -> dict[str, Any]:
    return {
        "id": roi.roi_id,
        "kind": roi.kind,
        "label": roi.label,
        "priority_bp": int(roi.priority_bp),
        "bbox_px": [int(roi.bbox_px[0]), int(roi.bbox_px[1]), int(roi.bbox_px[2]), int(roi.bbox_px[3])],
    }


def _norm_bbox_to_px(raw: Any, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
    except Exception:
        return None
    if x1 < 0.0 or y1 < 0.0 or x2 > 1.0 or y2 > 1.0 or x2 <= x1 or y2 <= y1:
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


def _to_bp(value: Any, *, default_bp: int) -> int:
    try:
        num = float(value)
    except Exception:
        return int(default_bp)
    if num <= 1.0:
        num *= 10000.0
    return int(max(0.0, min(10000.0, num)))


def _clean_text(value: Any) -> str:
    text = str(value or "").strip().replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _enum_or_default(value: Any, allowed: set[str], default: str) -> str:
    low = str(value or "").strip().casefold()
    return low if low in allowed else default


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = float(iw * ih)
    if inter <= 0.0:
        return 0.0
    area_a = float(max(1, (ax2 - ax1) * (ay2 - ay1)))
    area_b = float(max(1, (bx2 - bx1) * (by2 - by1)))
    union = max(1.0, area_a + area_b - inter)
    return inter / union


def _collect_rois(raw: dict[str, Any], *, width: int, height: int, max_rois: int) -> list[_Roi]:
    full = _Roi("full", "window", "full_image", 10000, (0, 0, int(width), int(height)))
    out: list[_Roi] = [full]
    rois = raw.get("rois", []) if isinstance(raw.get("rois"), list) else []
    for idx, item in enumerate(rois, start=1):
        if not isinstance(item, dict):
            continue
        bbox = _norm_bbox_to_px(item.get("bbox_norm"), width=width, height=height)
        if bbox is None:
            continue
        out.append(
            _Roi(
                roi_id=str(item.get("id") or f"roi_{idx}"),
                kind=_clean_text(item.get("kind")) or "other",
                label=_clean_text(item.get("label")),
                priority_bp=_to_bp(item.get("priority"), default_bp=6000),
                bbox_px=bbox,
            )
        )
    out.sort(key=lambda r: (-int(r.priority_bp), r.roi_id))
    dedup: list[_Roi] = [full]
    # Reserve room for deterministic coverage ROIs to avoid concentration
    # in a single pane when the thumbnail pass is sparse/noisy.
    model_cap = max(1, int(max_rois) - 4)
    for roi in out:
        if roi.roi_id == "full":
            continue
        keep = True
        for existing in dedup:
            if _iou(roi.bbox_px, existing.bbox_px) >= 0.9:
                keep = False
                break
        if keep:
            dedup.append(roi)
        if len(dedup) >= int(model_cap):
            break
    # Coverage backstop: add deterministic grid ROIs so high-res pass scans
    # the full desktop, even when model-proposed ROIs are concentrated.
    if len(dedup) < int(max_rois):
        fallback_specs = [
            ("grid_tl", (0.00, 0.00, 0.36, 0.56)),
            ("grid_tc", (0.30, 0.00, 0.70, 0.56)),
            ("grid_tr", (0.64, 0.00, 1.00, 0.56)),
            ("grid_bl", (0.00, 0.44, 0.36, 1.00)),
            ("grid_bc", (0.30, 0.44, 0.70, 1.00)),
            ("grid_br", (0.64, 0.44, 1.00, 1.00)),
        ]
        for roi_id, norm in fallback_specs:
            bbox = _norm_bbox_to_px(norm, width=width, height=height)
            if bbox is None:
                continue
            candidate = _Roi(roi_id=roi_id, kind="pane", label=roi_id, priority_bp=4500, bbox_px=bbox)
            keep = True
            for existing in dedup:
                if _iou(candidate.bbox_px, existing.bbox_px) >= 0.92:
                    keep = False
                    break
            if not keep:
                continue
            dedup.append(candidate)
            if len(dedup) >= int(max_rois):
                break
    return dedup


def _parse_elements(raw: dict[str, Any], *, parent_roi: _Roi) -> list[dict[str, Any]]:
    entries = raw.get("elements", []) if isinstance(raw.get("elements"), list) else []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        local = _norm_bbox_to_px(entry.get("bbox_norm"), width=_roi_w(parent_roi), height=_roi_h(parent_roi))
        if local is None:
            continue
        gx1 = int(parent_roi.bbox_px[0] + local[0])
        gy1 = int(parent_roi.bbox_px[1] + local[1])
        gx2 = int(parent_roi.bbox_px[0] + local[2])
        gy2 = int(parent_roi.bbox_px[1] + local[3])
        label = _clean_text(entry.get("text")) or _clean_text(entry.get("label"))
        if not label:
            continue
        state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
        interactable = bool(entry.get("interactable", False))
        el_type = _clean_text(entry.get("type")) or "other"
        out.append(
            {
                "type": el_type,
                "bbox": [gx1, gy1, gx2, gy2],
                "text": label,
                "interactable": interactable,
                "state": {
                    "enabled": bool(state.get("enabled", True)),
                    "selected": bool(state.get("selected", False)),
                    "focused": bool(state.get("focused", False)),
                    "expanded": bool(state.get("expanded", False)),
                },
                "children": [],
            }
        )
    return out


def _parse_windows(
    raw: dict[str, Any],
    *,
    width: int,
    height: int,
    parent_roi: _Roi | None,
) -> list[dict[str, Any]]:
    entries = raw.get("windows", []) if isinstance(raw.get("windows"), list) else []
    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        if parent_roi is None:
            bbox = _norm_bbox_to_px(entry.get("bbox_norm"), width=width, height=height)
        else:
            local = _norm_bbox_to_px(entry.get("bbox_norm"), width=_roi_w(parent_roi), height=_roi_h(parent_roi))
            if local is None:
                bbox = None
            else:
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
                "label": _clean_text(entry.get("label")),
                "app": _clean_text(entry.get("app")) or _clean_text(entry.get("label")),
                "context": _enum_or_default(entry.get("context"), {"host", "vdi", "unknown"}, "unknown"),
                "visibility": _enum_or_default(
                    entry.get("visibility"),
                    {"fully_visible", "partially_occluded", "unknown"},
                    "unknown",
                ),
                "z_hint_bp": _to_bp(entry.get("z_hint"), default_bp=5000),
                "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                "source_roi": parent_roi.roi_id if parent_roi else "thumbnail",
            }
        )
    return out


def _parse_facts(raw: dict[str, Any], *, parent_roi: _Roi) -> list[dict[str, Any]]:
    entries = raw.get("facts", []) if isinstance(raw.get("facts"), list) else []
    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        key = _clean_text(entry.get("key"))
        value = _clean_text(entry.get("value"))
        if not key or not value:
            continue
        out.append(
            {
                "fact_id": f"{parent_roi.roi_id}:f:{idx}",
                "key": key,
                "value": value,
                "confidence_bp": _to_bp(entry.get("confidence"), default_bp=7000),
                "source_roi": parent_roi.roi_id,
            }
        )
    return out


def _dedupe_elements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, int, int, int], str]] = set()
    for item in items:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        except Exception:
            continue
        kind = _clean_text(item.get("type")) or "other"
        text = _clean_text(item.get("text"))
        fp = (kind, bbox, text)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(
            {
                "type": kind,
                "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                "text": text,
                "interactable": bool(item.get("interactable", False)),
                "state": item.get("state", {}) if isinstance(item.get("state"), dict) else {},
                "children": item.get("children", []) if isinstance(item.get("children"), list) else [],
            }
        )
    out.sort(key=lambda e: (int(e["bbox"][1]), int(e["bbox"][0]), str(e.get("type") or ""), str(e.get("text") or "")))
    return out[:1200]


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
        duplicate = False
        for existing in out:
            eb = existing.get("bbox")
            if not isinstance(eb, list) or len(eb) != 4:
                continue
            ebt = (int(eb[0]), int(eb[1]), int(eb[2]), int(eb[3]))
            if _iou(bbox, ebt) >= 0.9 and app.casefold() == _clean_text(existing.get("app")).casefold():
                duplicate = True
                break
        if duplicate:
            continue
        out.append(
            {
                "window_id": str(item.get("window_id") or ""),
                "label": _clean_text(item.get("label")),
                "app": app,
                "context": _enum_or_default(item.get("context"), {"host", "vdi", "unknown"}, "unknown"),
                "visibility": _enum_or_default(
                    item.get("visibility"),
                    {"fully_visible", "partially_occluded", "unknown"},
                    "unknown",
                ),
                "z_hint_bp": int(item.get("z_hint_bp") or 5000),
                "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                "source_roi": _clean_text(item.get("source_roi")),
            }
        )
    out.sort(key=lambda w: (-int(w.get("z_hint_bp") or 0), str(w.get("app") or "")))
    return out[:160]


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
                "fact_id": _clean_text(item.get("fact_id")),
                "key": key,
                "value": value,
                "confidence_bp": int(item.get("confidence_bp") or 7000),
                "source_roi": _clean_text(item.get("source_roi")),
            }
        )
    out.sort(key=lambda f: (-int(f.get("confidence_bp") or 0), str(f.get("key") or ""), str(f.get("value") or "")))
    return out[:800]
