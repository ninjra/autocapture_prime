"""Time utilities for deterministic records.

Goals:
- Store timestamps in UTC with a stable Z suffix.
- Persist the timezone id and offset (minutes) used for local interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# Keep ZoneInfo as a runtime value (not a static type) so mypy/ruff do not
# complain about assigning None to a type.
ZoneInfo: Any
try:  # Python 3.9+
    from zoneinfo import ZoneInfo as _ZoneInfo  # type: ignore

    ZoneInfo = _ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def utc_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    # Use ISO 8601 with Z; keep microseconds only when present.
    text = dt_utc.isoformat()
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    return text


def utc_now_z() -> str:
    return utc_iso_z(datetime.now(timezone.utc))


def tz_offset_minutes(tzid: str, *, at_utc: datetime | None = None) -> int:
    tz = str(tzid or "UTC")
    base = at_utc or datetime.now(timezone.utc)
    base_utc = base.astimezone(timezone.utc)
    if tz.upper() == "UTC":
        return 0
    if ZoneInfo is None:
        # Best-effort fallback: report 0 when zoneinfo is unavailable.
        return 0
    try:
        local = base_utc.astimezone(ZoneInfo(tz))
        offset = local.utcoffset()
        if offset is None:
            return 0
        return int(offset.total_seconds() // 60)
    except Exception:
        return 0


@dataclass(frozen=True)
class NormalizedTime:
    ts_utc: str
    tzid: str
    offset_minutes: int


def normalize_time(
    *,
    tzid: str,
    at_utc: datetime | None = None,
) -> NormalizedTime:
    base = at_utc or datetime.now(timezone.utc)
    base_utc = base.astimezone(timezone.utc)
    tz = str(tzid or "UTC")
    return NormalizedTime(
        ts_utc=utc_iso_z(base_utc),
        tzid=tz,
        offset_minutes=tz_offset_minutes(tz, at_utc=base_utc),
    )
