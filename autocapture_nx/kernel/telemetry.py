"""In-process telemetry snapshot store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
from typing import Any


def _copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_telemetry_payload(category: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = _copy_payload(payload)
    stage = str(base.get("stage") or category).strip() or category
    run_id = str(base.get("run_id") or os.getenv("AUTOCAPTURE_RUN_ID") or "").strip()
    error_code = str(base.get("error_code") or "").strip()
    outcome = str(base.get("outcome") or "").strip().lower()
    if not outcome:
        outcome = "error" if error_code else "ok"
    duration_raw = base.get("duration_ms")
    try:
        duration_ms = float(duration_raw) if duration_raw is not None else 0.0
    except Exception:
        duration_ms = 0.0
    if duration_ms < 0:
        duration_ms = 0.0
    normalized = dict(base)
    normalized.update(
        {
        "schema_version": 1,
        "category": str(category),
        "ts_utc": str(base.get("ts_utc") or _utc_now()),
        "run_id": run_id,
        "stage": stage,
        "duration_ms": duration_ms,
        "outcome": outcome,
        "error_code": error_code,
        }
    )
    return normalized


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    pct = max(0.0, min(100.0, float(pct)))
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


@dataclass
class TelemetryStore:
    max_samples: int = 120
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _latest: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _history: dict[str, list[dict[str, Any]]] = field(default_factory=dict, init=False)

    def record(self, category: str, payload: dict[str, Any]) -> None:
        if not category:
            return
        entry = normalize_telemetry_payload(category, payload)
        with self._lock:
            self._latest[category] = entry
            history = self._history.setdefault(category, [])
            history.append(entry)
            if self.max_samples > 0 and len(history) > self.max_samples:
                del history[: len(history) - self.max_samples]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latest = {key: _copy_payload(value) for key, value in self._latest.items()}
            history = {key: [dict(item) for item in items] for key, items in self._history.items()}
        return {"latest": latest, "history": history}


_STORE = TelemetryStore()


def record_telemetry(category: str, payload: dict[str, Any]) -> None:
    _STORE.record(category, payload)


def telemetry_snapshot() -> dict[str, Any]:
    return _STORE.snapshot()
