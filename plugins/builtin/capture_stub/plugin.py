"""Stub capture plugin."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CaptureStub(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"capture.source": self}

    def start(self) -> None:
        raise NotImplementedError("Capture plugin not implemented")


def create_plugin(plugin_id: str, context: PluginContext) -> CaptureStub:
    return CaptureStub(plugin_id, context)
