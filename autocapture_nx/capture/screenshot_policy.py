"""Deterministic screenshot capture scheduling policy.

Keep this module dependency-free (no Windows-only imports) so it can be tested
in CI/WSL environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScreenshotSchedule:
    mode: str  # "active" | "idle"
    interval_s: float
    force_interval_s: float
    idle_seconds: float | None


def schedule_from_config(
    cfg: dict[str, Any] | None,
    *,
    idle_seconds: float | None,
) -> ScreenshotSchedule:
    """Compute screenshot interval and forced-store interval.

    Rules:
    - If activity scheduling is enabled: choose active vs idle interval based on idle_seconds.
    - If idle_seconds is missing: assume active by default (fail-open on capture frequency).
    - In active: force_interval_s = 0.0 (duplicates skipped).
    - In idle: force_interval_s = idle_interval_s (store at least one per interval even if duplicate).
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    activity = cfg.get("activity", {}) if isinstance(cfg.get("activity", {}), dict) else {}
    enabled = bool(activity.get("enabled", False))

    # Legacy mode: constant fps_target with whatever dedupe.force_interval_s is configured to.
    if not enabled:
        fps_target = int(cfg.get("fps_target", 2) or 2)
        interval_s = 1.0 / max(1, fps_target)
        dedupe_cfg = cfg.get("dedupe", {}) if isinstance(cfg.get("dedupe", {}), dict) else {}
        force_s = float(dedupe_cfg.get("force_interval_s", 0) or 0)
        return ScreenshotSchedule(mode="active", interval_s=float(interval_s), force_interval_s=float(force_s), idle_seconds=idle_seconds)

    active_window_s = float(activity.get("active_window_s", 3.0) or 3.0)
    active_interval_s = float(activity.get("active_interval_s", 0.5) or 0.5)
    idle_interval_s = float(activity.get("idle_interval_s", 60.0) or 60.0)
    assume_active_when_missing = bool(activity.get("assume_active_when_missing", True))

    # Clamp to safe bounds: never busy-loop.
    active_interval_s = max(0.05, float(active_interval_s))
    idle_interval_s = max(active_interval_s, float(idle_interval_s))

    if idle_seconds is None:
        mode = "active" if assume_active_when_missing else "idle"
    else:
        mode = "active" if float(idle_seconds) < float(active_window_s) else "idle"

    if mode == "active":
        return ScreenshotSchedule(
            mode="active",
            interval_s=float(active_interval_s),
            force_interval_s=0.0,
            idle_seconds=idle_seconds,
        )
    return ScreenshotSchedule(
        mode="idle",
        interval_s=float(idle_interval_s),
        force_interval_s=float(idle_interval_s),
        idle_seconds=idle_seconds,
    )

