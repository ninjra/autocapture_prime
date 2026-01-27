"""Runtime governor plugin for mode transitions and budget gating."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture.runtime.governor import RuntimeGovernor as CoreGovernor, GovernorDecision


MODES = {
    "ACTIVE_CAPTURE_ONLY",
    "IDLE_DRAIN",
    "USER_QUERY",
}


class RuntimeGovernor(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        runtime_cfg = context.config.get("runtime", {})
        idle_window = int(runtime_cfg.get("idle_window_s", 45))
        suspend_workers = bool(runtime_cfg.get("mode_enforcement", {}).get("suspend_workers", True))
        self._core = CoreGovernor(idle_window_s=idle_window, suspend_workers=suspend_workers)
        self._core.update_config(context.config)

    def capabilities(self) -> dict[str, Any]:
        return {"runtime.governor": self}

    def decide(self, signals: dict[str, Any]) -> GovernorDecision:
        return self._core.decide(signals)

    def next_mode(self, signals: dict[str, Any]) -> str:
        # Backwards-compatible helper used by older callers/tests.
        return self.decide(signals).mode

    def should_preempt(self, signals: dict[str, Any] | None = None) -> bool:
        return self._core.should_preempt(signals)

    def lease(self, job_name: str, estimated_ms: int, *, heavy: bool = True):
        return self._core.lease(job_name, estimated_ms, heavy=heavy)

    def budget_snapshot(self):
        return self._core.budget_snapshot()


def create_plugin(plugin_id: str, context: PluginContext) -> RuntimeGovernor:
    return RuntimeGovernor(plugin_id, context)
