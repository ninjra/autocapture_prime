"""SST stage hook plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst.stage_plugins import MatchIdsPlugin

def create_plugin(plugin_id: str, context: PluginContext) -> MatchIdsPlugin:
    return MatchIdsPlugin(plugin_id, context)

