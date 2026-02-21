"""Capture spool for durable segment storage."""

from __future__ import annotations

import json
import os
from pathlib import Path

from autocapture.capture.models import CaptureSegment


class CaptureSpool:
    def __init__(self, root: str | Path, *, fsync: bool = True) -> None:
        self.root = Path(root)
        self._fsync = bool(fsync)
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
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
                if self._fsync:
                    handle.flush()
                    os.fsync(handle.fileno())
            return True
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"spool_corrupt:{path}") from exc
            if existing == payload:
                return True
            raise RuntimeError(f"spool_collision:{path}")

    def has(self, segment_id: str) -> bool:
        return self._path(segment_id).exists()

    def list_segments(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))
