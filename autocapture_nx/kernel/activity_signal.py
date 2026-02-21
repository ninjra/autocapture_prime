"""Sidecar-provided activity/idle signal reader.

Foreground gating requires a reliable notion of whether the user is active.
When capture + input hooks are moved to a Windows sidecar, the sidecar must
persist an activity signal file under the shared DataRoot that this repo can
read to gate heavy processing (OCR/VLM/embeddings).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ActivitySignal:
    ts_utc: str
    idle_seconds: float
    user_active: bool
    source: str | None = None
    seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_utc": self.ts_utc,
            "idle_seconds": float(self.idle_seconds),
            "user_active": bool(self.user_active),
            "source": self.source,
            "seq": self.seq,
        }


def _parse_ts_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_max_age_s(config: dict[str, Any]) -> float:
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    activity = runtime.get("activity", {}) if isinstance(runtime, dict) else {}
    if not isinstance(activity, dict):
        return 5.0
    for key in ("fresh_signal_max_age_s", "max_signal_age_s", "signal_max_age_s"):
        raw = activity.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except Exception:
            continue
        if val > 0.0:
            return val
    return 5.0


def is_activity_signal_fresh(
    signal: ActivitySignal | None,
    config: dict[str, Any],
    *,
    now_utc: datetime | None = None,
) -> bool:
    if signal is None:
        return False
    parsed = _parse_ts_utc(signal.ts_utc)
    if parsed is None:
        return False
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    max_age_s = _freshness_max_age_s(config)
    age_s = (now - parsed).total_seconds()
    if age_s < 0:
        age_s = 0.0
    return age_s <= max_age_s


def _candidate_paths(config: dict[str, Any]) -> list[Path]:
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    activity = runtime.get("activity", {}) if isinstance(runtime, dict) else {}
    if isinstance(activity, dict):
        for key in ("sidecar_signal_path", "signal_path"):
            raw = activity.get(key)
            if isinstance(raw, str) and raw.strip():
                return [Path(raw.strip())]

    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = storage.get("data_dir", "data") if isinstance(storage, dict) else "data"
    root = Path(str(data_dir))
    return [
        root / "activity" / "activity_signal.json",
        root / "activity_signal.json",
    ]


def load_activity_signal(config: dict[str, Any]) -> ActivitySignal | None:
    """Best-effort read of the sidecar activity signal.

    Returns None if the signal is missing or invalid; callers must fail closed
    unless an explicit 'assume_idle_when_missing' override is enabled.
    """

    for path in _candidate_paths(config):
        try:
            if not path.exists():
                continue
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        ts_utc = obj.get("ts_utc")
        idle_seconds = obj.get("idle_seconds")
        user_active = obj.get("user_active")
        if not isinstance(ts_utc, str) or not ts_utc.strip():
            continue
        if idle_seconds is None:
            continue
        try:
            idle_f = float(idle_seconds)
        except Exception:
            continue
        if not isinstance(user_active, bool):
            try:
                user_active = bool(user_active)
            except Exception:
                continue
        source = obj.get("source")
        if not isinstance(source, str):
            source = None
        seq = obj.get("seq")
        if not isinstance(seq, int):
            try:
                seq = int(seq) if seq is not None else None
            except Exception:
                seq = None
        return ActivitySignal(
            ts_utc=ts_utc.strip(),
            idle_seconds=idle_f,
            user_active=bool(user_active),
            source=source.strip() if isinstance(source, str) and source.strip() else None,
            seq=seq,
        )
    return None
