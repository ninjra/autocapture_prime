"""VLM-backed UI parse stage hook for SST."""

from __future__ import annotations

import json
from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.processing.sst.utils import clamp_bbox


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
        providers = _providers(self._get_vlm())
        max_providers = int(cfg.get("max_providers", 1))
        if max_providers > 0:
            providers = providers[:max_providers]
        for provider_id, provider in providers:
            try:
                response = provider.extract(frame_bytes)
                text = str(response.get("text", "") or "")
            except Exception:
                continue
            element_graph = _parse_element_graph(text, tokens, frame_bbox, provider_id=str(provider_id))
            if element_graph:
                return {"element_graph": element_graph}
        return None

    def _get_vlm(self) -> Any | None:
        try:
            return self.context.get_capability("vision.extractor")
        except Exception:
            return None


def create_plugin(plugin_id: str, context: PluginContext) -> VLMUIStageHook:
    return VLMUIStageHook(plugin_id, context)


def _providers(capability: Any | None) -> list[tuple[str, Any]]:
    if capability is None:
        return []
    target = capability
    if hasattr(target, "target"):
        target = getattr(target, "target")
    if hasattr(target, "items"):
        try:
            items = list(target.items())
        except Exception:
            items = []
        if items:
            return [(str(pid), provider) for pid, provider in items]
    return [("vision.extractor", capability)]


def _parse_element_graph(
    text: str,
    tokens: list[dict[str, Any]],
    frame_bbox: tuple[int, int, int, int],
    *,
    provider_id: str,
) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list):
        return None
    state_id = "vlm"
    elements: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_element(el: dict[str, Any], parent_id: str | None, depth: int, order: int) -> None:
        el_type = str(el.get("type", "unknown"))
        bbox_raw = el.get("bbox")
        bbox = _coerce_bbox(bbox_raw, frame_bbox)
        if bbox is None:
            return
        label = el.get("text")
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
    return {"state_id": state_id, "elements": tuple(elements), "edges": tuple(edges)}


def _coerce_bbox(bbox: Any, frame_bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    except Exception:
        return None
    return clamp_bbox((x1, y1, x2, y2), width=frame_bbox[2], height=frame_bbox[3])


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
