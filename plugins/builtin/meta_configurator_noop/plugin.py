"""No-op configurator plugin."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class NoopConfigurator(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"meta.configurator": self}

    def configure(self, config: dict[str, Any]) -> dict[str, Any]:
        return config


def create_plugin(plugin_id: str, context: PluginContext) -> NoopConfigurator:
    return NoopConfigurator(plugin_id, context)
