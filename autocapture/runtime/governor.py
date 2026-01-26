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
    def __init__(self, idle_window_s: int = 45, suspend_workers: bool = True) -> None:
        self.idle_window_s = idle_window_s
        self.suspend_workers = suspend_workers

    def decide(self, signals: dict[str, Any]) -> GovernorDecision:
        idle_seconds = float(signals.get("idle_seconds", 0))
        user_active = bool(signals.get("user_active", False))
        query_intent = bool(signals.get("query_intent", False))
        suspend_workers = bool(signals.get("suspend_workers", self.suspend_workers))

        if query_intent:
            return GovernorDecision(mode="USER_QUERY")
        if user_active and suspend_workers:
            return GovernorDecision(mode="ACTIVE_CAPTURE_ONLY")
        if idle_seconds >= self.idle_window_s:
            return GovernorDecision(mode="IDLE_DRAIN")
        if user_active and not suspend_workers:
            return GovernorDecision(mode="IDLE_DRAIN")
        return GovernorDecision(mode="ACTIVE_CAPTURE_ONLY")


def create_governor(plugin_id: str) -> RuntimeGovernor:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    runtime_cfg = config.get("runtime", {})
    idle_window_s = int(runtime_cfg.get("idle_window_s", 45))
    suspend_workers = bool(runtime_cfg.get("mode_enforcement", {}).get("suspend_workers", True))
    return RuntimeGovernor(idle_window_s=idle_window_s, suspend_workers=suspend_workers)
