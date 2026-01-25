"""Metrics endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/metrics")
def metrics():
    return {
        "counters": {},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
