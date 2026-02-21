"""Diff helpers for research scout."""

from __future__ import annotations

from typing import Any


def _item_key(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("title") or item.get("hash") or item)


def diff_items(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    prev_map = {_item_key(item): item for item in previous}
    cur_map = {_item_key(item): item for item in current}
    added = [cur_map[k] for k in cur_map.keys() - prev_map.keys()]
    removed = [prev_map[k] for k in prev_map.keys() - cur_map.keys()]
    unchanged = [cur_map[k] for k in cur_map.keys() & prev_map.keys()]
    total = max(len(prev_map), 1)
    change_numer = len(added) + len(removed)
    change_ratio = change_numer / total
    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "change_ratio": f"{change_ratio:.6f}",
        "change_numer": change_numer,
        "change_denom": total,
    }


def diff_with_threshold(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    threshold: float = 0.1,
) -> dict[str, Any]:
    diff = diff_items(previous, current)
    change_numer = diff.get("change_numer", 0)
    change_denom = diff.get("change_denom", 1)
    ratio = change_numer / change_denom if change_denom else 0.0
    changed = ratio >= threshold
    diff["changed"] = changed
    diff["threshold"] = f"{threshold:.6f}"
    return diff
