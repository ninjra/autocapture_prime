"""Capture data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureSegment:
    segment_id: str
    ts_utc: str
    blob_id: str
    metadata: dict
