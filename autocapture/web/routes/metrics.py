"""Metrics endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from fastapi import APIRouter

from autocapture_nx.kernel.telemetry import telemetry_snapshot

router = APIRouter()


def _sanitize_metrics(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_metrics(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_sanitize_metrics(item) for item in value]
    return value


@router.get("/api/metrics")
def metrics():
    return {
        "counters": {},
        "telemetry": _sanitize_metrics(telemetry_snapshot()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
