"""Capture spool for durable segment storage."""

from __future__ import annotations

import json
from pathlib import Path

from autocapture.capture.models import CaptureSegment


class CaptureSpool:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, segment_id: str) -> Path:
        return self.root / f"{segment_id}.json"

    def append(self, segment: CaptureSegment) -> bool:
        path = self._path(segment.segment_id)
        payload = {
            "segment_id": segment.segment_id,
            "ts_utc": segment.ts_utc,
            "blob_id": segment.blob_id,
            "metadata": segment.metadata,
        }
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True))
            return True
        except FileExistsError:
            return False

    def has(self, segment_id: str) -> bool:
        return self._path(segment_id).exists()

    def list_segments(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))
