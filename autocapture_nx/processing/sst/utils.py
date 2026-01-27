"""Utility helpers for SST processing."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable

from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps

BBox = tuple[int, int, int, int]


_WS_RE = re.compile(r"\s+")


def now_ts_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def ts_utc_to_ms(ts_utc: str | None) -> int:
    if not ts_utc:
        return now_ts_ms()
    ts = ts_utc
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return int(datetime.fromisoformat(ts).timestamp() * 1000)
    except ValueError:
        return now_ts_ms()


def bp(value: float | int, *, scale: int = 10000) -> int:
    if isinstance(value, int):
        if value < 0:
            return 0
        if value > scale:
            return scale
        return value
    if value <= 0:
        return 0
    if value >= 1:
        return scale
    return int(round(value * scale))


def norm_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = _WS_RE.sub(" ", normalized).strip()
    return normalized


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_canonical(obj: Any) -> str:
    payload = canonical_dumps(obj).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hamming_distance(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return max(len(a), len(b))
    return sum(1 for ca, cb in zip(a, b) if ca != cb)


def clamp_bbox(bbox: BBox, *, width: int, height: int) -> BBox:
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(int(x1), width))
    y1 = max(0, min(int(y1), height))
    x2 = max(0, min(int(x2), width))
    y2 = max(0, min(int(y2), height))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return (x1, y1, x2, y2)


def bbox_area(bbox: BBox) -> int:
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def bbox_iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = bbox_area((ix1, iy1, ix2, iy2))
    if inter <= 0:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def bbox_union(bboxes: Iterable[BBox]) -> BBox:
    xs1: list[int] = []
    ys1: list[int] = []
    xs2: list[int] = []
    ys2: list[int] = []
    for x1, y1, x2, y2 in bboxes:
        xs1.append(x1)
        ys1.append(y1)
        xs2.append(x2)
        ys2.append(y2)
    if not xs1:
        return (0, 0, 0, 0)
    return (min(xs1), min(ys1), max(xs2), max(ys2))


def stable_sorted(items: Iterable[Any], key) -> list[Any]:
    return sorted(list(items), key=key)

