"""No-op policy plugin."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class NoopPolicy(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"meta.policy": self}

    def apply(self, permissions: dict[str, Any]) -> dict[str, Any]:
        return permissions


def create_plugin(plugin_id: str, context: PluginContext) -> NoopPolicy:
    return NoopPolicy(plugin_id, context)
