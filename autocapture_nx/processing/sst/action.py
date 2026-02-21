"""Pixels-only action inference."""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component

from .utils import bbox_iou, hash_canonical


ACTION_KINDS = (
    "click",
    "double_click",
    "right_click",
    "type",
    "scroll",
    "drag",
    "key_shortcut",
    "unknown",
)


def infer_action(
    *,
    delta_event: dict[str, Any] | None,
    cursor_prev: dict[str, Any] | None,
    cursor_curr: dict[str, Any] | None,
    prev_state: dict[str, Any] | None,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    if not delta_event or not prev_state:
        return None
    candidates = [
        _cand_type(delta_event, prev_state, state),
        _cand_click(delta_event, prev_state, cursor_prev, cursor_curr),
        _cand_scroll(delta_event, prev_state, state),
        _cand_drag(delta_event, prev_state, cursor_prev, cursor_curr),
    ]
    candidates = [c for c in candidates if c["confidence_bp"] > 0]
    if not candidates:
        primary = _unknown(delta_event)
        alternatives: list[dict[str, Any]] = []
    else:
        candidates.sort(key=lambda c: (-c["confidence_bp"], c["kind"], str(c.get("target_element_id") or "")))
        primary = candidates[0]
        alternatives = [c for c in candidates[1:3] if c["kind"] != primary["kind"]]
        if primary["confidence_bp"] < 5000 and not alternatives:
            alternatives = [_unknown(delta_event)]

    impact = _impact(delta_event)
    action_id = _action_id(delta_event, primary, alternatives, impact)
    return {
        "action_id": action_id,
        "from_state_id": prev_state["state_id"],
        "to_state_id": state["state_id"],
        "ts_ms": int(state.get("ts_ms", prev_state.get("ts_ms", 0))),
        "primary": primary,
        "alternatives": tuple(alternatives),
        "impact": impact,
    }


def _cand_type(delta: dict[str, Any], prev_state: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    focus = state.get("focus_element_id") or prev_state.get("focus_element_id")
    if not focus:
        return _cand("type", None, 0, {"reason": "no_focus"})
    text_changes = sum(1 for c in delta.get("changes", ()) if c.get("kind") == "element.changed" and c.get("detail", {}).get("text_changed"))
    if text_changes <= 0:
        return _cand("type", focus, 0, {"reason": "no_text_change"})
    conf = min(9800, 5500 + 500 * text_changes)
    return _cand("type", focus, conf, {"text_changes": text_changes})


def _cand_click(
    delta: dict[str, Any],
    prev_state: dict[str, Any],
    cursor_prev: dict[str, Any] | None,
    cursor_curr: dict[str, Any] | None,
) -> dict[str, Any]:
    cursor = cursor_curr or cursor_prev
    if not cursor:
        return _cand("click", None, 0, {"reason": "no_cursor"})
    target = _cursor_target(prev_state, cursor)
    if not target:
        return _cand("click", None, 0, {"reason": "no_target"})
    state_changes = sum(1 for c in delta.get("changes", ()) if c.get("kind") in {"element.changed", "element.added"})
    if state_changes <= 0:
        return _cand("click", target, 0, {"reason": "no_state_change"})
    conf = min(9600, 5200 + 400 * state_changes)
    return _cand("click", target, conf, {"state_changes": state_changes})


def _cand_scroll(delta: dict[str, Any], prev_state: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    prev_elements = {e["element_id"]: e for e in prev_state.get("element_graph", {}).get("elements", ())}
    elements = {e["element_id"]: e for e in state.get("element_graph", {}).get("elements", ())}
    shifts = []
    for element_id in sorted(set(prev_elements) & set(elements)):
        old = prev_elements[element_id]
        new = elements[element_id]
        dy = (new["bbox"][1] - old["bbox"][1]) + (new["bbox"][3] - old["bbox"][3])
        if dy:
            shifts.append(dy)
    if not shifts:
        return _cand("scroll", None, 0, {"reason": "no_shift"})
    avg_shift = sum(shifts) // max(1, len(shifts))
    magnitude = abs(avg_shift)
    if magnitude < 20:
        return _cand("scroll", None, 0, {"reason": "small_shift", "avg_shift": avg_shift})
    conf = min(9300, 5000 + min(3000, magnitude * 40))
    return _cand("scroll", None, conf, {"avg_shift": avg_shift, "shift_count": len(shifts)})


def _cand_drag(
    delta: dict[str, Any],
    prev_state: dict[str, Any],
    cursor_prev: dict[str, Any] | None,
    cursor_curr: dict[str, Any] | None,
) -> dict[str, Any]:
    if not cursor_curr:
        return _cand("drag", None, 0, {"reason": "no_cursor"})
    changed = [c for c in delta.get("changes", ()) if c.get("kind") == "element.changed" and c.get("detail", {}).get("bbox_changed")]
    if not changed:
        return _cand("drag", None, 0, {"reason": "no_bbox_change"})
    target = _cursor_target(prev_state, cursor_curr)
    if not target:
        target = changed[0].get("target_id")
    move_conf = 0
    if cursor_prev and cursor_curr:
        dx = abs(cursor_curr["bbox"][0] - cursor_prev["bbox"][0])
        dy = abs(cursor_curr["bbox"][1] - cursor_prev["bbox"][1])
        move_conf = min(2000, (dx + dy) * 20)
    conf = min(9100, 5200 + 300 * len(changed) + move_conf)
    return _cand("drag", target, conf, {"changed": len(changed)})


def _cursor_target(state: dict[str, Any], cursor: dict[str, Any]) -> str | None:
    cb = cursor.get("bbox")
    if not cb:
        return None
    candidates = []
    for el in state.get("element_graph", {}).get("elements", ()):
        if not el.get("interactable", False):
            continue
        iou = bbox_iou(cb, el.get("bbox", (0, 0, 0, 0)))
        if iou <= 0:
            continue
        candidates.append((iou, el))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]["bbox"][1], item[1]["bbox"][0], item[1]["element_id"]))
    return candidates[0][1]["element_id"]


def _impact(delta: dict[str, Any]) -> dict[str, bool]:
    summary = delta.get("summary", {})
    removed = int(summary.get("element_removed", 0))
    added = int(summary.get("element_added", 0))
    table_changes = int(summary.get("table_cell_changed", 0))
    deleted = removed >= 3 or table_changes >= 12
    created = added > 0 and removed == 0
    modified = bool(summary.get("total_changes", 0))
    return {"created": created, "modified": modified, "deleted": deleted}


def _action_id(
    delta_event: dict[str, Any],
    primary: dict[str, Any],
    alternatives: list[dict[str, Any]],
    impact: dict[str, bool],
) -> str:
    key = {
        "delta": delta_event.get("delta_id"),
        "primary": {"kind": primary.get("kind"), "target": primary.get("target_element_id"), "conf": primary.get("confidence_bp")},
        "alts": [{"k": a.get("kind"), "t": a.get("target_element_id"), "c": a.get("confidence_bp")} for a in alternatives],
        "impact": impact,
    }
    digest = hash_canonical(key)[:20]
    return encode_record_id_component(f"action-{delta_event.get('delta_id')}-{primary.get('kind')}-{digest}")


def _unknown(delta_event: dict[str, Any]) -> dict[str, Any]:
    return _cand("unknown", None, 4000, {"delta_id": delta_event.get("delta_id")})


def _cand(kind: str, target: str | None, confidence_bp: int, evidence: dict[str, Any]) -> dict[str, Any]:
    if kind not in ACTION_KINDS:
        kind = "unknown"
    return {
        "kind": kind,
        "target_element_id": target,
        "confidence_bp": int(confidence_bp),
        "evidence": evidence,
    }

