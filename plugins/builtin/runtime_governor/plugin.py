"""Runtime governor plugin for mode transitions."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


MODES = {
    "ACTIVE_CAPTURE_ONLY",
    "IDLE_DRAIN",
    "USER_QUERY",
}


class RuntimeGovernor(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"runtime.governor": self}

    def next_mode(self, signals: dict[str, Any]) -> str:
        # Signals: user_active (bool), idle_seconds (int), query_intent (bool)
        idle_seconds = int(signals.get("idle_seconds", 0))
        user_active = bool(signals.get("user_active", False))
        query_intent = bool(signals.get("query_intent", False))
        idle_window = int(self.context.config.get("runtime", {}).get("idle_window_s", 45))

        if query_intent:
            return "USER_QUERY"
        if user_active:
            return "ACTIVE_CAPTURE_ONLY"
        if idle_seconds >= idle_window:
            return "IDLE_DRAIN"
        return "ACTIVE_CAPTURE_ONLY"


def create_plugin(plugin_id: str, context: PluginContext) -> RuntimeGovernor:
    return RuntimeGovernor(plugin_id, context)
