"""Stable element ID matching across states."""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component

from .utils import bbox_iou, hash_canonical, norm_text


def match_ids(prev_state: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any]:
    if not prev_state:
        return state
    prev_graph = prev_state.get("element_graph", {})
    graph = state.get("element_graph", {})
    prev_elements = list(prev_graph.get("elements", ()))
    elements = list(graph.get("elements", ()))
    if not prev_elements or not elements:
        return state

    width = max(1, int(state.get("width", 1)))
    height = max(1, int(state.get("height", 1)))
    prev_sig = {el["element_id"]: _signature(el, prev_state, width, height) for el in prev_elements}
    sig = {el["element_id"]: _signature(el, state, width, height) for el in elements}

    pairs: list[tuple[float, str, str]] = []
    for new_id, new_el in ((el["element_id"], el) for el in elements):
        for old_id, old_el in ((el["element_id"], el) for el in prev_elements):
            cost = _cost(old_el, new_el, prev_sig[old_id], sig[new_id])
            pairs.append((cost, old_id, new_id))
    pairs.sort(key=lambda item: (item[0], item[1], item[2]))

    assigned_old: set[str] = set()
    assigned_new: set[str] = set()
    mapping: dict[str, str] = {}
    for cost, old_id, new_id in pairs:
        if cost > 0.7:
            break
        if old_id in assigned_old or new_id in assigned_new:
            continue
        assigned_old.add(old_id)
        assigned_new.add(new_id)
        mapping[new_id] = old_id

    used_ids = {el["element_id"] for el in prev_elements}
    tracked: list[dict[str, Any]] = []
    for el in elements:
        new_id = el["element_id"]
        element_id = mapping.get(new_id, new_id)
        if element_id in used_ids and element_id not in mapping.values():
            element_id = encode_record_id_component(f"{element_id}-{state['state_id']}")
        used_ids.add(element_id)
        tracked.append({**el, "element_id": element_id})

    tracked.sort(key=lambda e: (e.get("z", 0), e["bbox"][1], e["bbox"][0], e["element_id"]))
    graph = {**graph, "elements": tuple(tracked)}
    return {**state, "element_graph": graph}


def _signature(el: dict[str, Any], state: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    bbox = el.get("bbox", (0, 0, 0, 0))
    rel = (
        int(round(int(bbox[0]) * 10000 / width)),
        int(round(int(bbox[1]) * 10000 / height)),
        int(round(int(bbox[2]) * 10000 / width)),
        int(round(int(bbox[3]) * 10000 / height)),
    )
    text_hash = _text_hash(el, state)
    parent_id = el.get("parent_id")
    parent_sig = None
    if parent_id:
        parent = _element_by_id(state, parent_id)
        if parent:
            pb = parent.get("bbox", (0, 0, 0, 0))
            parent_sig = (
                parent.get("type"),
                int(round(int(pb[0]) * 10000 / width)),
                int(round(int(pb[1]) * 10000 / height)),
            )
    return {
        "type": el.get("type", "unknown"),
        "rel_bbox": rel,
        "text_hash": text_hash,
        "parent_sig": parent_sig,
    }


def _text_hash(el: dict[str, Any], state: dict[str, Any]) -> str:
    refs = el.get("text_refs", ())
    if not refs:
        return "empty"
    tokens = state.get("tokens", ())
    token_map = {t.get("token_id"): t for t in tokens}
    texts = [norm_text(str(token_map.get(ref, {}).get("norm_text", ""))) for ref in refs]
    texts = [t for t in texts if t]
    if not texts:
        return "empty"
    return hash_canonical(texts)[:16]


def _element_by_id(state: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    for el in state.get("element_graph", {}).get("elements", ()):
        if el.get("element_id") == element_id:
            return el
    return None


def _cost(old_el: dict[str, Any], new_el: dict[str, Any], old_sig: dict[str, Any], new_sig: dict[str, Any]) -> float:
    iou = bbox_iou(old_el.get("bbox", (0, 0, 0, 0)), new_el.get("bbox", (0, 0, 0, 0)))
    cost = 1.0 - iou
    if old_sig["type"] != new_sig["type"]:
        cost += 0.5
    text_distance = _text_distance(old_sig["text_hash"], new_sig["text_hash"])
    cost += 0.3 * text_distance
    if old_sig["parent_sig"] != new_sig["parent_sig"]:
        cost += 0.2
    return cost


def _text_distance(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if not a or not b or a == "empty" or b == "empty":
        return 1.0
    # Hash prefixes provide a cheap stable distance proxy.
    shared = sum(1 for ca, cb in zip(a, b) if ca == cb)
    return max(0.0, 1.0 - shared / max(1, min(len(a), len(b))))

