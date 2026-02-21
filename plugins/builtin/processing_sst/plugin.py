"""Builtin SST processing pipeline plugin."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.processing.sst.pipeline import SSTPipeline


class _ContextSystem:
    def __init__(self, context: PluginContext) -> None:
        self.config = context.config
        self._context = context

    def has(self, name: str) -> bool:
        try:
            self._context.get_capability(name)
            return True
        except Exception:
            return False

    def get(self, name: str) -> Any:
        return self._context.get_capability(name)


class SSTPipelinePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        system = _ContextSystem(context)
        self._pipeline = SSTPipeline(system, extractor_id=plugin_id, extractor_version="0.1.0")

    def capabilities(self) -> dict[str, Any]:
        return {"processing.pipeline": self._pipeline}


def create_plugin(plugin_id: str, context: PluginContext) -> SSTPipelinePlugin:
    return SSTPipelinePlugin(plugin_id, context)

