"""Prompt bundle plugin for PromptOps."""

from __future__ import annotations

from typing import Any

from autocapture.promptops.sources import PromptBundle
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class PromptBundlePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config.get("promptops", {}) if isinstance(context.config, dict) else {}
        root = cfg.get("bundle_root")
        self._bundle = PromptBundle(root=str(root)) if root else PromptBundle()

    def capabilities(self) -> dict[str, Any]:
        return {"prompt.bundle": self._bundle}


def create_plugin(plugin_id: str, context: PluginContext) -> PromptBundlePlugin:
    return PromptBundlePlugin(plugin_id, context)
