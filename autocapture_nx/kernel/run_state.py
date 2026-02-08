"""Run state persistence helpers.

This centralizes timestamp normalization and ensures run_state.json is stable
and operator-friendly across timezones and DST changes.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.atomic_write import atomic_write_json
from autocapture_nx.kernel.timebase import normalize_time, utc_iso_z, tz_offset_minutes


@dataclass(frozen=True)
class RunStatePayload:
    run_id: str
    state: str
    ts_utc: str
    tzid: str
    offset_minutes: int
    started_at: str | None = None
    stopped_at: str | None = None
    ledger_head: str | None = None
    locks: dict[str, str | None] | None = None
    config_hash: str | None = None
    safe_mode: bool | None = None
    safe_mode_reason: str | None = None


def build_run_state_payload(
    *,
    run_id: str,
    state: str,
    tzid: str,
    started_at: str | None = None,
    stopped_at: str | None = None,
    ledger_head: str | None = None,
    locks: dict[str, str | None] | None = None,
    config_hash: str | None = None,
    safe_mode: bool | None = None,
    safe_mode_reason: str | None = None,
    now_utc: datetime | None = None,
) -> RunStatePayload:
    tz = str(tzid or "UTC")
    base = now_utc or datetime.now(timezone.utc)
    norm = normalize_time(tzid=tz, at_utc=base)
    # Normalize started/stopped timestamps when provided.
    def _norm_ts(value: str | None) -> str | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return utc_iso_z(dt)
        except Exception:
            return str(value)

    return RunStatePayload(
        run_id=str(run_id),
        state=str(state),
        ts_utc=norm.ts_utc,
        tzid=tz,
        offset_minutes=int(tz_offset_minutes(tz, at_utc=base)),
        started_at=_norm_ts(started_at),
        stopped_at=_norm_ts(stopped_at),
        ledger_head=str(ledger_head) if ledger_head else None,
        locks=dict(locks) if isinstance(locks, dict) else None,
        config_hash=str(config_hash) if config_hash else None,
        safe_mode=bool(safe_mode) if safe_mode is not None else None,
        safe_mode_reason=str(safe_mode_reason) if safe_mode_reason else None,
    )


def write_run_state(path: str | Path, payload: RunStatePayload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, asdict(payload), sort_keys=True, indent=None)

