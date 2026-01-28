"""SST stage hook plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst.stage_plugins import ExtractTablePlugin

def create_plugin(plugin_id: str, context: PluginContext) -> ExtractTablePlugin:
    return ExtractTablePlugin(plugin_id, context)

