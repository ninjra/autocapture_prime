"""SST stage hook plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst.stage_plugins import PreprocessNormalizePlugin

def create_plugin(plugin_id: str, context: PluginContext) -> PreprocessNormalizePlugin:
    return PreprocessNormalizePlugin(plugin_id, context)

