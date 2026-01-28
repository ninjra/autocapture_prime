"""Runtime scheduler plugin wrapping the core scheduler."""

from __future__ import annotations

from typing import Any

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Scheduler
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class RuntimeScheduler(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._governor = self._resolve_governor()
        self._scheduler = Scheduler(self._governor)

    def _resolve_governor(self) -> RuntimeGovernor:
        try:
            governor = self.context.get_capability("runtime.governor")
        except Exception:
            governor = None
        if governor is None:
            governor = RuntimeGovernor()
        if hasattr(governor, "update_config"):
            try:
                governor.update_config(self.context.config)
            except Exception:
                pass
        return governor

    @property
    def governor(self) -> RuntimeGovernor:
        return self._governor

    def set_governor(self, governor: RuntimeGovernor) -> None:
        self._governor = governor
        self._scheduler = Scheduler(self._governor)

    def capabilities(self) -> dict[str, Any]:
        return {"runtime.scheduler": self}

    def enqueue(self, job) -> None:
        self._scheduler.enqueue(job)

    def run_pending(self, signals: dict) -> list[str]:
        return self._scheduler.run_pending(signals)

    def last_stats(self):
        return self._scheduler.last_stats()


def create_plugin(plugin_id: str, context: PluginContext) -> RuntimeScheduler:
    return RuntimeScheduler(plugin_id, context)
