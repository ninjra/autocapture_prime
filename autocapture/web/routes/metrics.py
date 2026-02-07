"""Metrics endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from fastapi import APIRouter, Request

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
def metrics(request: Request):
    snap = telemetry_snapshot()
    latest = snap.get("latest", {}) if isinstance(snap, dict) else {}
    history = snap.get("history", {}) if isinstance(snap, dict) else {}

    def _hist_seconds(category: str) -> list[float]:
        rows = history.get(category, []) if isinstance(history, dict) else []
        out: list[float] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                val = row.get("seconds")
                if isinstance(val, (int, float)) and math.isfinite(float(val)):
                    out.append(float(val))
        return out

    def _pct(values: list[float], pct: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        if len(ordered) == 1:
            return float(ordered[0])
        pct = max(0.0, min(100.0, float(pct)))
        rank = (pct / 100.0) * (len(ordered) - 1)
        lo = int(rank)
        hi = min(lo + 1, len(ordered) - 1)
        frac = rank - lo
        return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)

    ttfr_samples = _hist_seconds("ttfr")
    ttfr = {
        "samples": len(ttfr_samples),
        "p50_s": _pct(ttfr_samples, 50.0),
        "p95_s": _pct(ttfr_samples, 95.0),
        "min_s": min(ttfr_samples) if ttfr_samples else None,
        "max_s": max(ttfr_samples) if ttfr_samples else None,
    }

    plugin_timing = None
    try:
        plugin_timing = request.app.state.facade.plugins_timing()
    except Exception:
        plugin_timing = None

    return {
        "counters": {},
        "ttfr_seconds": ttfr,
        "plugin_timing": plugin_timing,
        "telemetry": _sanitize_metrics({"latest": latest, "history": history}),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
