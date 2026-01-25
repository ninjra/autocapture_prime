"""Activity signal tracking for runtime governance."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ActivitySnapshot:
    user_active: bool
    idle_seconds: float
    query_intent: bool


class ActivitySignal:
    def __init__(self, active_threshold_s: float = 2.0) -> None:
        self._last_event_ts: float | None = None
        self._active_threshold_s = active_threshold_s

    def record_activity(self) -> None:
        self._last_event_ts = time.time()

    def idle_seconds(self) -> float:
        if self._last_event_ts is None:
            return float("inf")
        return max(0.0, time.time() - self._last_event_ts)

    def snapshot(self, query_intent: bool = False) -> ActivitySnapshot:
        idle = self.idle_seconds()
        user_active = idle < self._active_threshold_s
        return ActivitySnapshot(user_active=user_active, idle_seconds=idle, query_intent=query_intent)


def create_activity_signal(plugin_id: str) -> ActivitySignal:
    return ActivitySignal()
