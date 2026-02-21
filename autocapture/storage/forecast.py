"""Disk usage forecasting utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ForecastResult:
    days_remaining: int | None
    samples: int
    trend_bytes_per_day: int | None
    evidence_bytes_per_day: int | None
    derived_bytes_per_day: int | None


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _pressure_samples(journal_path: Path) -> list[tuple[datetime, int, int | None, int | None]]:
    if not journal_path.exists():
        return []
    samples: list[tuple[datetime, int, int | None, int | None]] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("event_type") != "disk.pressure":
            continue
        payload = entry.get("payload", {})
        free_bytes = payload.get("free_bytes")
        if free_bytes is None:
            free_gb = payload.get("free_gb")
            if free_gb is None:
                continue
            free_bytes = int(free_gb) * (1024 ** 3)
        try:
            free_bytes = int(free_bytes)
        except Exception:
            continue
        ts = _parse_ts(entry.get("ts_utc"))
        if ts is None:
            continue
        evidence_bytes = payload.get("evidence_bytes")
        derived_bytes = payload.get("derived_bytes")
        try:
            evidence_bytes = int(evidence_bytes) if evidence_bytes is not None else None
        except Exception:
            evidence_bytes = None
        try:
            derived_bytes = int(derived_bytes) if derived_bytes is not None else None
        except Exception:
            derived_bytes = None
        samples.append((ts, free_bytes, evidence_bytes, derived_bytes))
    return samples


def _trend_per_day(first: int | None, last: int | None, delta_seconds: float) -> int | None:
    if first is None or last is None:
        return None
    if delta_seconds <= 0:
        return None
    return int(((last - first) / delta_seconds) * 86400)


def estimate_days_remaining(
    samples: Iterable[tuple[datetime, int, int | None, int | None]]
) -> ForecastResult:
    ordered = sorted(samples, key=lambda item: item[0])
    if len(ordered) < 2:
        return ForecastResult(
            days_remaining=None,
            samples=len(ordered),
            trend_bytes_per_day=None,
            evidence_bytes_per_day=None,
            derived_bytes_per_day=None,
        )
    first_ts, first_free, first_evidence, first_derived = ordered[0]
    last_ts, last_free, last_evidence, last_derived = ordered[-1]
    delta_seconds = (last_ts - first_ts).total_seconds()
    if delta_seconds <= 0:
        return ForecastResult(
            days_remaining=None,
            samples=len(ordered),
            trend_bytes_per_day=None,
            evidence_bytes_per_day=None,
            derived_bytes_per_day=None,
        )
    delta_free = last_free - first_free
    bytes_per_second = delta_free / delta_seconds
    if bytes_per_second >= 0:
        return ForecastResult(
            days_remaining=None,
            samples=len(ordered),
            trend_bytes_per_day=None,
            evidence_bytes_per_day=_trend_per_day(first_evidence, last_evidence, delta_seconds),
            derived_bytes_per_day=_trend_per_day(first_derived, last_derived, delta_seconds),
        )
    bytes_per_day = int(bytes_per_second * 86400)
    days_remaining = int(max(0, last_free // abs(bytes_per_day))) if bytes_per_day != 0 else None
    return ForecastResult(
        days_remaining=days_remaining,
        samples=len(ordered),
        trend_bytes_per_day=bytes_per_day,
        evidence_bytes_per_day=_trend_per_day(first_evidence, last_evidence, delta_seconds),
        derived_bytes_per_day=_trend_per_day(first_derived, last_derived, delta_seconds),
    )


def forecast_from_journal(data_dir: str) -> ForecastResult:
    journal_path = Path(data_dir) / "journal.ndjson"
    return estimate_days_remaining(_pressure_samples(journal_path))
