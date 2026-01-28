"""SST stage hook plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst.stage_plugins import BuildStatePlugin

def create_plugin(plugin_id: str, context: PluginContext) -> BuildStatePlugin:
    return BuildStatePlugin(plugin_id, context)

