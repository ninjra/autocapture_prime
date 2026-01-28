"""Metrics endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter

from autocapture_nx.kernel.telemetry import telemetry_snapshot

router = APIRouter()


@router.get("/api/metrics")
def metrics():
    return {
        "counters": {},
        "telemetry": telemetry_snapshot(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
