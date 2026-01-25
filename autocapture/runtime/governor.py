"""Runtime governor enforcing heavy-work gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MODES = {
    "ACTIVE_CAPTURE_ONLY",
    "IDLE_DRAIN",
    "USER_QUERY",
}


@dataclass
class GovernorDecision:
    mode: str


class RuntimeGovernor:
    def __init__(self, idle_window_s: int = 45) -> None:
        self.idle_window_s = idle_window_s

    def decide(self, signals: dict[str, Any]) -> GovernorDecision:
        idle_seconds = float(signals.get("idle_seconds", 0))
        user_active = bool(signals.get("user_active", False))
        query_intent = bool(signals.get("query_intent", False))

        if query_intent:
            return GovernorDecision(mode="USER_QUERY")
        if user_active:
            return GovernorDecision(mode="ACTIVE_CAPTURE_ONLY")
        if idle_seconds >= self.idle_window_s:
            return GovernorDecision(mode="IDLE_DRAIN")
        return GovernorDecision(mode="ACTIVE_CAPTURE_ONLY")


def create_governor(plugin_id: str) -> RuntimeGovernor:
    return RuntimeGovernor()
