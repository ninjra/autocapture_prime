"""Deterministic screen structure parser (screen.parse.v1)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


def _bbox(raw: Any) -> list[int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            x1, y1, x2, y2 = [int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3])]
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            return [max(0, x1), max(0, y1), max(0, x2), max(0, y2)]
        except Exception:
            return [0, 0, 0, 0]
    return [0, 0, 0, 0]


def _node_id(*, frame_id: str, kind: str, text: str, bbox: list[int], parent_id: str, ordinal: int, depth: int) -> str:
    seed = {
        "frame_id": frame_id,
        "kind": kind,
        "text": text[:256],
        "bbox": bbox,
        "parent_id": parent_id,
        "ordinal": int(ordinal),
        "depth": int(depth),
    }
    blob = json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"node_{hashlib.sha256(blob).hexdigest()[:16]}"


def _sort_key(node: dict[str, Any]) -> tuple[int, int, int, int, str]:
    b = _bbox(node.get("bbox"))
    return (int(b[1]), int(b[0]), int(b[3]), int(b[2]), str(node.get("node_id") or ""))


class ScreenParsePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._max_nodes = max(1, int(cfg.get("max_nodes") or 4096))

    def capabilities(self) -> dict[str, Any]:
        return {"screen.parse.v1": self}

    def parse(self, image_bytes: bytes, *, frame_id: str = "", layout: dict[str, Any] | None = None) -> dict[str, Any]:
        source_backend = "screen_parse_no_layout"
        source_provider_id = ""
        resolved = layout if isinstance(layout, dict) else {}
        if not resolved:
            try:
                extractor = self.context.get_capability("vision.extractor")
            except Exception:
                extractor = None
            if extractor is not None and hasattr(extractor, "extract") and callable(getattr(extractor, "extract")):
                try:
                    result = extractor.extract(bytes(image_bytes or b""))
                    if isinstance(result, dict):
                        source_backend = str(result.get("backend") or "screen_parse_vision_extract").strip()
                        source_provider_id = str(result.get("source_provider_id") or "").strip()
                        candidate = result.get("layout")
                        if isinstance(candidate, dict):
                            resolved = candidate
                except Exception:
                    resolved = {}
        elements = resolved.get("elements", []) if isinstance(resolved, dict) else []
        if not isinstance(elements, list):
            elements = []

        frame = str(frame_id or "").strip() or "frame_unknown"
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        def walk(items: list[Any], parent_id: str = "", depth: int = 0) -> list[str]:
            out_ids: list[str] = []
            for idx, item in enumerate(items):
                if len(nodes) >= self._max_nodes:
                    break
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("type") or "node").strip() or "node"
                text = str(item.get("text") or item.get("label") or "").strip()
                bbox = _bbox(item.get("bbox"))
                nid = _node_id(
                    frame_id=frame,
                    kind=kind,
                    text=text,
                    bbox=bbox,
                    parent_id=parent_id,
                    ordinal=idx,
                    depth=depth,
                )
                node: dict[str, Any] = {
                    "node_id": nid,
                    "kind": kind,
                    "text": text,
                    "bbox": bbox,
                    "children": [],
                }
                nodes.append(node)
                out_ids.append(nid)
                if parent_id:
                    edges.append({"from": parent_id, "to": nid, "relation": "contains"})
                child_items = item.get("children", [])
                if isinstance(child_items, list) and child_items:
                    node["children"] = walk(child_items, nid, depth + 1)
            return out_ids

        root_nodes = walk(elements, "", 0)
        if not nodes:
            fallback_id = _node_id(
                frame_id=frame,
                kind="screen",
                text="",
                bbox=[0, 0, 0, 0],
                parent_id="",
                ordinal=0,
                depth=0,
            )
            nodes.append(
                {
                    "node_id": fallback_id,
                    "kind": "screen",
                    "text": "",
                    "bbox": [0, 0, 0, 0],
                    "children": [],
                }
            )
            root_nodes = [fallback_id]

        nodes.sort(key=_sort_key)
        edges.sort(key=lambda e: (str(e.get("from") or ""), str(e.get("to") or ""), str(e.get("relation") or "")))
        return {
            "schema_version": 1,
            "frame_id": frame,
            "nodes": nodes,
            "edges": edges,
            "root_nodes": root_nodes,
            "source_backend": source_backend,
            "source_provider_id": source_provider_id,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> ScreenParsePlugin:
    return ScreenParsePlugin(plugin_id, context)
