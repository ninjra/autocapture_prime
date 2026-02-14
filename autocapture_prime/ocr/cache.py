from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .base import OcrSpan


def cache_key(frame_sha256: str, roi: tuple[int, int, int, int] | None, config_hash: str) -> str:
    payload = {
        "config_hash": config_hash,
        "frame_sha256": frame_sha256,
        "roi": list(roi) if roi else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_cache(path: Path) -> list[OcrSpan] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    spans = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict):
            continue
        bbox_raw = row.get("bbox")
        if not (isinstance(bbox_raw, list) and len(bbox_raw) == 4):
            continue
        spans.append(
            OcrSpan(
                text=str(row.get("text") or ""),
                confidence=float(row.get("confidence") or 0.0),
                bbox=(int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])),
                reading_order=int(row.get("reading_order") or 0),
                language=str(row.get("language") or ""),
            )
        )
    return spans


def save_cache(path: Path, spans: list[OcrSpan]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: list[dict[str, Any]] = []
    for span in spans:
        payload.append(
            {
                "text": span.text,
                "confidence": span.confidence,
                "bbox": list(span.bbox),
                "reading_order": span.reading_order,
                "language": span.language,
            }
        )
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
