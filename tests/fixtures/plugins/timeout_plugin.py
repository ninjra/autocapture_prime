"""Test-only plugin used to validate subprocess RPC timeout behavior."""

from __future__ import annotations

import time
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class Sleeper(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"test.sleeper": self}

    def sleep(self, seconds: float) -> dict[str, Any]:
        time.sleep(float(seconds))
        return {"slept": float(seconds)}


def create_plugin(plugin_id: str, context: PluginContext) -> Sleeper:
    return Sleeper(plugin_id, context)

