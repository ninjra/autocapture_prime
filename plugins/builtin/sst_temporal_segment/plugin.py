"""SST stage hook plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst.stage_plugins import TemporalSegmentPlugin

def create_plugin(plugin_id: str, context: PluginContext) -> TemporalSegmentPlugin:
    return TemporalSegmentPlugin(plugin_id, context)

