"""VLM-backed UI parse stage hook for SST."""

from __future__ import annotations

import json
import re
from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.processing.sst.utils import clamp_bbox
from autocapture_nx.kernel.providers import capability_providers


class VLMUIStageHook(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._config = context.config if isinstance(context.config, dict) else {}

    def capabilities(self) -> dict[str, Any]:
        return {"processing.stage.hooks": self}

    def stages(self) -> list[str]:
        return ["ui.parse"]

    def run_stage(self, stage: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if stage != "ui.parse":
            return None
        cfg = self._config.get("processing", {}).get("sst", {}).get("ui_vlm", {})
        if not bool(cfg.get("enabled", False)):
            return None
        frame_bytes = payload.get("frame_bytes")
        tokens = payload.get("tokens", [])
        frame_bbox = payload.get("frame_bbox")
        if not frame_bytes or not isinstance(tokens, list) or not frame_bbox:
            return None
        use_cached_tokens = bool(cfg.get("use_cached_tokens", False))
        if use_cached_tokens:
            cached_graph = _parse_element_graph_from_cached_vlm_tokens(tokens, frame_bbox)
            if cached_graph is not None:
                return {"element_graph": cached_graph}
        providers = _providers(self._get_vlm())
        max_providers = int(cfg.get("max_providers", 1))
        best_graph: dict[str, Any] | None = None
        best_score = -10**9
        successful = 0
        unavailable_backends = {"unavailable", "openai_compat_unparsed", "heuristic", "toy.vlm", "toy_vlm"}
        non_recoverable_backends = {"unavailable", "heuristic", "toy.vlm", "toy_vlm"}
        for provider_id, provider in providers:
            backend = ""
            try:
                response = provider.extract(frame_bytes)
                raw_layout = response.get("layout") if isinstance(response, dict) else None
                text = ""
                if isinstance(response, dict):
                    text = str(
                        response.get("text")
                        or response.get("text_plain")
                        or response.get("caption")
                        or ""
                    )
                backend = str(response.get("backend", "") or "").strip().casefold() if isinstance(response, dict) else ""
            except Exception:
                continue
            raw_state_id = ""
            raw_elements: list[Any] = []
            if isinstance(raw_layout, dict):
                raw_state_id = str(raw_layout.get("state_id") or "").strip().casefold()
                raw_backend = str(raw_layout.get("source_backend") or "").strip().casefold()
                if not backend and raw_backend:
                    backend = raw_backend
                raw_values = raw_layout.get("elements", [])
                if isinstance(raw_values, list):
                    raw_elements = raw_values
            if not backend and raw_state_id.startswith("vlm"):
                backend = "layout_inferred"
            if backend in non_recoverable_backends:
                continue
            backend_unavailable = backend in unavailable_backends or not backend
            if backend_unavailable and not text and not (raw_state_id.startswith("vlm") and len(raw_elements) > 0):
                continue
            source: str | dict[str, Any]
            if isinstance(raw_layout, dict) and len(raw_elements) > 0:
                source = raw_layout
            else:
                source = text
            state_id = raw_state_id if raw_state_id else _state_id_from_vlm_backend(backend)
            element_graph = _parse_element_graph(
                source,
                tokens,
                frame_bbox,
                provider_id=str(provider_id),
                state_id=state_id,
            )
            if element_graph is None and isinstance(source, str):
                recovered_layout = _recover_layout_from_partial_json(source)
                if recovered_layout:
                    state_id = "vlm"
                    backend = "openai_compat_text_recovered"
                    element_graph = _parse_element_graph(
                        recovered_layout,
                        tokens,
                        frame_bbox,
                        provider_id=str(provider_id),
                        state_id=state_id,
                    )
            if element_graph:
                if len(element_graph.get("elements", ())) <= 1:
                    continue
                successful += 1
                element_graph["source_backend"] = backend or "layout_inferred"
                element_graph["source_provider_id"] = str(provider_id)
                score = _provider_result_score(str(provider_id), state_id, backend)
                if score > best_score:
                    best_score = score
                    best_graph = element_graph
                if best_score >= 180:
                    break
                if max_providers > 0 and successful >= max_providers and best_score >= 120:
                    break
        if best_graph is not None:
            return {"element_graph": best_graph}
        return None

    def _get_vlm(self) -> Any | None:
        try:
            return self.context.get_capability("vision.extractor")
        except Exception:
            return None


def create_plugin(plugin_id: str, context: PluginContext) -> VLMUIStageHook:
    return VLMUIStageHook(plugin_id, context)


def _providers(capability: Any | None) -> list[tuple[str, Any]]:
    providers = capability_providers(capability, "vision.extractor")
    providers.sort(key=lambda pair: (-_provider_priority(pair[0]), str(pair[0])))
    return providers


def _provider_priority(provider_id: str) -> int:
    low = str(provider_id or "").strip().casefold()
    score = 0
    if "vllm" in low or "localhost" in low or "openai" in low:
        score += 60
    if "transformers" in low or "qwen" in low or "internvl" in low or "mai" in low:
        score += 20
    if "stub" in low or "basic" in low or "toy" in low or "heuristic" in low:
        score -= 40
    return score


def _provider_result_score(provider_id: str, state_id: str, backend: str) -> int:
    state_low = str(state_id or "").strip().casefold()
    backend_low = str(backend or "").strip().casefold()
    score = _provider_priority(provider_id)
    if state_low == "vlm":
        score += 100
    elif state_low.startswith("vlm"):
        score += 40
    if backend_low == "openai_compat_layout":
        score += 80
    elif backend_low and backend_low not in {"heuristic", "toy.vlm", "toy_vlm", "openai_compat_unparsed", "unavailable"}:
        score += 40
    if backend_low in {"heuristic", "toy.vlm", "toy_vlm", "openai_compat_unparsed", "unavailable"}:
        score -= 35
    return score


def _parse_element_graph_from_cached_vlm_tokens(
    tokens: list[dict[str, Any]],
    frame_bbox: tuple[int, int, int, int],
) -> dict[str, Any] | None:
    best_graph: dict[str, Any] | None = None
    best_score = -10**9
    for token in tokens:
        if not isinstance(token, dict):
            continue
        source = str(token.get("source") or "").strip().casefold()
        provider_id = str(token.get("provider_id") or "vision.extractor").strip() or "vision.extractor"
        if source != "vlm" and not provider_id.casefold().startswith("builtin.vlm."):
            continue
        candidate_text = str(token.get("text") or token.get("norm_text") or "")
        if not candidate_text.strip():
            continue
        graph = _parse_element_graph(candidate_text, tokens, frame_bbox, provider_id=provider_id, state_id="vlm")
        backend = "cached_vlm_token"
        if graph is None:
            recovered = _recover_layout_from_partial_json(candidate_text)
            if recovered:
                graph = _parse_element_graph(recovered, tokens, frame_bbox, provider_id=provider_id, state_id="vlm")
                backend = "openai_compat_text_recovered"
        if graph is None:
            continue
        if len(graph.get("elements", ())) <= 1:
            continue
        graph["source_backend"] = backend
        graph["source_provider_id"] = provider_id
        score = _provider_priority(provider_id) + int(len(graph.get("elements", ())))
        if score > best_score:
            best_score = score
            best_graph = graph
    return best_graph


def _parse_element_graph(
    source: str | dict[str, Any],
    tokens: list[dict[str, Any]],
    frame_bbox: tuple[int, int, int, int],
    *,
    provider_id: str,
    state_id: str = "vlm",
) -> dict[str, Any] | None:
    if isinstance(source, dict):
        data = source
    else:
        try:
            data = json.loads(source)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list):
        return None
    if not _validate_element_schema(raw_elements):
        return None
    elements: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_element(el: dict[str, Any], parent_id: str | None, depth: int, order: int) -> None:
        el_type = str(el.get("type", "unknown"))
        bbox_raw = el.get("bbox")
        bbox = _coerce_bbox(bbox_raw, frame_bbox)
        if bbox is None:
            return
        label = el.get("text")
        if label in (None, ""):
            label = el.get("label")
        state = el.get("state") if isinstance(el.get("state"), dict) else {}
        interactable = bool(el.get("interactable", _default_interactable(el_type)))
        token_ids = _tokens_for_bbox(tokens, bbox)
        element_id = encode_record_id_component(f"{el_type}-{provider_id}-{depth}-{order}-{bbox}")
        elements.append(
            {
                "element_id": element_id,
                "type": el_type,
                "bbox": bbox,
                "text_refs": tuple(token_ids),
                "label": label,
                "interactable": interactable,
                "state": {
                    "enabled": bool(state.get("enabled", True)),
                    "selected": bool(state.get("selected", False)),
                    "focused": bool(state.get("focused", False)),
                    "expanded": bool(state.get("expanded", False)),
                },
                "parent_id": parent_id,
                "children_ids": tuple(),
                "z": int(depth),
                "app_hint": None,
            }
        )
        if parent_id:
            edges.append({"src": parent_id, "dst": element_id, "kind": "contains"})
        children = el.get("children")
        if isinstance(children, list):
            for idx, child in enumerate(children):
                if isinstance(child, dict):
                    add_element(child, element_id, depth + 1, idx)

    root_id = encode_record_id_component(f"root-{provider_id}")
    elements.append(
        {
            "element_id": root_id,
            "type": "window",
            "bbox": frame_bbox,
            "text_refs": tuple(_tokens_for_bbox(tokens, frame_bbox)),
            "label": None,
            "interactable": False,
            "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
            "parent_id": None,
            "children_ids": tuple(),
            "z": 0,
            "app_hint": None,
        }
    )
    for idx, item in enumerate(raw_elements):
        if isinstance(item, dict):
            add_element(item, root_id, 1, idx)
    _link_children(elements)
    elements.sort(key=lambda e: (e["z"], e["bbox"][1], e["bbox"][0], e["element_id"]))
    out: dict[str, Any] = {"state_id": state_id, "elements": tuple(elements), "edges": tuple(edges)}
    ui_state = data.get("ui_state")
    if isinstance(ui_state, dict):
        out["ui_state"] = ui_state
    # Preserve optional structured arrays when present so downstream plugins can
    # consume VLM-native windows/facts without re-parsing OCR text.
    for key in ("windows", "facts", "rois", "roi_reports"):
        value = data.get(key)
        if isinstance(value, list):
            out[key] = value
    return out


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
        element_type = str(match.group("type") or "").strip().casefold() or "other"
        if element_type in {"", "null"}:
            continue
        bbox_values = _parse_bbox_values(match.group("bbox") or "")
        if bbox_values is None:
            continue
        snippet = f"{match.group('mid') or ''}{match.group('tail') or ''}"
        label = ""
        m_text = re.search(r'"text"\s*:\s*"([^"]{1,180})"', snippet, flags=re.IGNORECASE)
        if m_text:
            label = str(m_text.group(1) or "").strip()
        if not label:
            m_label = re.search(r'"label"\s*:\s*"([^"]{1,180})"', snippet, flags=re.IGNORECASE)
            if m_label:
                label = str(m_label.group(1) or "").strip()
        elements.append(
            {
                "type": element_type,
                "bbox": [float(bbox_values[0]), float(bbox_values[1]), float(bbox_values[2]), float(bbox_values[3])],
                "text": label,
                "interactable": bool(_default_interactable(element_type)),
                "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                "children": [],
            }
        )
        if len(elements) >= 32:
            break
    if len(elements) < 1:
        return {}
    return {"elements": elements, "edges": [], "state_id": "vlm", "source_backend": "openai_compat_text_recovered"}


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


def _state_id_from_vlm_backend(backend: str) -> str:
    value = str(backend or "").strip().casefold()
    if value in {"heuristic", "toy.vlm", "toy_vlm", "ocr_heuristic", "vlm_heuristic"}:
        return "vlm_heuristic"
    return "vlm"


def _validate_element_schema(elements: list[Any]) -> bool:
    def _valid_element(el: Any) -> bool:
        if not isinstance(el, dict):
            return False
        if not isinstance(el.get("type"), str):
            return False
        bbox = el.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            return False
        try:
            _ = [float(v) for v in bbox]
        except Exception:
            return False
        children = el.get("children")
        if children is None:
            return True
        if not isinstance(children, list):
            return False
        return all(_valid_element(child) for child in children)

    return all(_valid_element(el) for el in elements)


def _coerce_bbox(bbox: Any, frame_bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x1f, y1f, x2f, y2f = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    except Exception:
        return None
    width = int(frame_bbox[2])
    height = int(frame_bbox[3])
    if width <= 0 or height <= 0:
        return None
    if (
        0.0 <= x1f <= 1.0
        and 0.0 <= y1f <= 1.0
        and 0.0 <= x2f <= 1.0
        and 0.0 <= y2f <= 1.0
    ):
        x1 = int(round(x1f * float(width)))
        y1 = int(round(y1f * float(height)))
        x2 = int(round(x2f * float(width)))
        y2 = int(round(y2f * float(height)))
    else:
        x1 = int(round(x1f))
        y1 = int(round(y1f))
        x2 = int(round(x2f))
        y2 = int(round(y2f))
    return clamp_bbox((x1, y1, x2, y2), width=width, height=height)


def _tokens_for_bbox(tokens: list[dict[str, Any]], bbox: tuple[int, int, int, int]) -> list[str]:
    out = []
    for token in tokens:
        tb = token.get("bbox")
        if not tb or len(tb) != 4:
            continue
        mx = (tb[0] + tb[2]) // 2
        my = (tb[1] + tb[3]) // 2
        if bbox[0] <= mx < bbox[2] and bbox[1] <= my < bbox[3]:
            out.append(token.get("token_id"))
    return [t for t in out if t]


def _link_children(elements: list[dict[str, Any]]) -> None:
    by_parent: dict[str, list[str]] = {}
    for el in elements:
        pid = el.get("parent_id")
        if not pid:
            continue
        by_parent.setdefault(pid, []).append(el["element_id"])
    for el in elements:
        children = sorted(by_parent.get(el["element_id"], []))
        el["children_ids"] = tuple(children)


def _default_interactable(el_type: str) -> bool:
    return el_type in {"button", "textbox", "checkbox", "radio", "dropdown", "tab", "menu", "icon"}
