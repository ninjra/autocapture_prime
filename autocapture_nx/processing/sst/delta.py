"""Delta event construction."""

from __future__ import annotations

import difflib
from typing import Any, Iterable

from autocapture_nx.kernel.ids import encode_record_id_component

from .utils import bbox_iou, hash_canonical, norm_text


def build_delta(
    *,
    prev_state: dict[str, Any] | None,
    state: dict[str, Any],
    bbox_shift_px: int,
    table_match_iou_bp: int,
) -> dict[str, Any] | None:
    if not prev_state:
        return None
    changes: list[dict[str, Any]] = []
    changes.extend(_diff_elements(prev_state, state, bbox_shift_px=bbox_shift_px))
    changes.extend(_diff_tables(prev_state, state, table_match_iou_bp=table_match_iou_bp))
    changes.extend(_diff_code(prev_state, state))
    changes.extend(_diff_charts(prev_state, state))
    if not changes:
        return None
    changes.sort(key=_change_sort_key)
    summary = _summarize(changes)
    delta_id = _delta_id(prev_state["state_id"], state["state_id"], summary, changes)
    return {
        "delta_id": delta_id,
        "from_state_id": prev_state["state_id"],
        "to_state_id": state["state_id"],
        "ts_ms": int(state.get("ts_ms", prev_state.get("ts_ms", 0))),
        "changes": tuple(changes),
        "summary": summary,
    }


def _diff_elements(prev_state: dict[str, Any], state: dict[str, Any], *, bbox_shift_px: int) -> list[dict[str, Any]]:
    prev_elements = {el["element_id"]: el for el in prev_state.get("element_graph", {}).get("elements", ())}
    elements = {el["element_id"]: el for el in state.get("element_graph", {}).get("elements", ())}
    changes: list[dict[str, Any]] = []
    prev_ids = set(prev_elements.keys())
    new_ids = set(elements.keys())
    for element_id in sorted(new_ids - prev_ids):
        changes.append({"kind": "element.added", "target_id": element_id, "detail": {}})
    for element_id in sorted(prev_ids - new_ids):
        changes.append({"kind": "element.removed", "target_id": element_id, "detail": {}})
    for element_id in sorted(prev_ids & new_ids):
        old = prev_elements[element_id]
        new = elements[element_id]
        detail: dict[str, Any] = {}
        if _bbox_shift(old.get("bbox"), new.get("bbox")) > bbox_shift_px:
            detail["bbox_changed"] = True
        if _text_hash(prev_state, old) != _text_hash(state, new):
            detail["text_changed"] = True
        if old.get("state") != new.get("state"):
            detail["state_changed"] = True
        if detail:
            changes.append({"kind": "element.changed", "target_id": element_id, "detail": detail})
    return changes


def _diff_tables(prev_state: dict[str, Any], state: dict[str, Any], *, table_match_iou_bp: int) -> list[dict[str, Any]]:
    prev_tables = list(prev_state.get("tables", ()))
    tables = list(state.get("tables", ()))
    if not prev_tables or not tables:
        return []
    threshold = max(0.0, min(1.0, table_match_iou_bp / 10000.0))
    matches: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for new in tables:
        for old in prev_tables:
            iou = bbox_iou(old.get("bbox", (0, 0, 0, 0)), new.get("bbox", (0, 0, 0, 0)))
            matches.append((iou, old, new))
    matches.sort(key=lambda item: (-item[0], item[1]["table_id"], item[2]["table_id"]))
    used_old: set[str] = set()
    used_new: set[str] = set()
    paired: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for iou, old, new in matches:
        if iou < threshold:
            break
        if old["table_id"] in used_old or new["table_id"] in used_new:
            continue
        used_old.add(old["table_id"])
        used_new.add(new["table_id"])
        paired.append((old, new))
    changes: list[dict[str, Any]] = []
    for old, new in paired:
        old_cells = {(c["r"], c["c"]): c for c in old.get("cells", ())}
        new_cells = {(c["r"], c["c"]): c for c in new.get("cells", ())}
        addresses = sorted(set(old_cells) | set(new_cells))
        for addr in addresses:
            before = norm_text(str(old_cells.get(addr, {}).get("norm_text", "")))
            after = norm_text(str(new_cells.get(addr, {}).get("norm_text", "")))
            if before == after:
                continue
            r, c = addr
            changes.append(
                {
                    "kind": "table.cell_changed",
                    "target_id": new["table_id"],
                    "detail": {"r": int(r), "c": int(c), "before": before, "after": after},
                }
            )
    return changes


def _diff_code(prev_state: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    prev_blocks = {b["code_id"]: b for b in prev_state.get("code_blocks", ())}
    blocks = {b["code_id"]: b for b in state.get("code_blocks", ())}
    if not prev_blocks or not blocks:
        return []
    changes: list[dict[str, Any]] = []
    for code_id in sorted(set(prev_blocks) & set(blocks)):
        old = prev_blocks[code_id]
        new = blocks[code_id]
        if old.get("text") == new.get("text"):
            continue
        diff = _line_diff(old.get("lines", ()), new.get("lines", ()))
        changes.append({"kind": "code.changed", "target_id": code_id, "detail": diff})
    return changes


def _diff_charts(prev_state: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    prev_charts = {c["chart_id"]: c for c in prev_state.get("charts", ())}
    charts = {c["chart_id"]: c for c in state.get("charts", ())}
    if not prev_charts or not charts:
        return []
    changes: list[dict[str, Any]] = []
    for chart_id in sorted(set(prev_charts) & set(charts)):
        old = prev_charts[chart_id]
        new = charts[chart_id]
        if old.get("ticks_y") != new.get("ticks_y"):
            changes.append(
                {
                    "kind": "chart.ticks_changed",
                    "target_id": chart_id,
                    "detail": {"before": tuple(old.get("ticks_y", ())), "after": tuple(new.get("ticks_y", ()))},
                }
            )
    return changes


def _bbox_shift(a: Any, b: Any) -> int:
    if not a or not b:
        return 0
    ax1, ay1, ax2, ay2 = (int(a[0]), int(a[1]), int(a[2]), int(a[3]))
    bx1, by1, bx2, by2 = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
    return abs(ax1 - bx1) + abs(ay1 - by1) + abs(ax2 - bx2) + abs(ay2 - by2)


def _text_hash(state: dict[str, Any], element: dict[str, Any]) -> str:
    refs = element.get("text_refs", ())
    if not refs:
        return "empty"
    token_map = {t.get("token_id"): t for t in state.get("tokens", ())}
    texts = [token_map.get(ref, {}).get("norm_text", "") for ref in refs]
    texts = [norm_text(str(t)) for t in texts if t]
    if not texts:
        return "empty"
    return hash_canonical(texts)[:16]


def _line_diff(old_lines: Iterable[str], new_lines: Iterable[str]) -> dict[str, Any]:
    old_list = [str(x) for x in old_lines]
    new_list = [str(x) for x in new_lines]
    matcher = difflib.SequenceMatcher(a=old_list, b=new_list, autojunk=False)
    changes: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append(
            {
                "tag": tag,
                "old": tuple(old_list[i1:i2]),
                "new": tuple(new_list[j1:j2]),
                "i1": int(i1),
                "i2": int(i2),
                "j1": int(j1),
                "j2": int(j2),
            }
        )
    return {"changes": tuple(changes)}


def _change_sort_key(change: dict[str, Any]) -> tuple[str, str, str]:
    detail = change.get("detail", {})
    try:
        detail_key = hash_canonical(detail)
    except Exception:
        detail_key = str(detail)
    return (str(change.get("kind", "")), str(change.get("target_id", "")), detail_key)


def _summarize(changes: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "element_added": 0,
        "element_removed": 0,
        "element_changed": 0,
        "table_cell_changed": 0,
        "code_changed": 0,
        "chart_changed": 0,
        "total_changes": len(changes),
    }
    for change in changes:
        kind = change.get("kind")
        if kind == "element.added":
            summary["element_added"] += 1
        elif kind == "element.removed":
            summary["element_removed"] += 1
        elif kind == "element.changed":
            summary["element_changed"] += 1
        elif kind == "table.cell_changed":
            summary["table_cell_changed"] += 1
        elif kind == "code.changed":
            summary["code_changed"] += 1
        elif kind == "chart.ticks_changed":
            summary["chart_changed"] += 1
    return summary


def _delta_id(from_state_id: str, to_state_id: str, summary: dict[str, int], changes: list[dict[str, Any]]) -> str:
    key = {
        "from": from_state_id,
        "to": to_state_id,
        "summary": summary,
        "change_hashes": [hash_canonical({"k": c.get("kind"), "t": c.get("target_id"), "d": c.get("detail")}) for c in changes],
    }
    digest = hash_canonical(key)[:20]
    return encode_record_id_component(f"delta-{from_state_id}-{to_state_id}-{digest}")
