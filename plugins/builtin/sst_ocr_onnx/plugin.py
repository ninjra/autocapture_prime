"""SST stage hook plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst.stage_plugins import OcrOnnxPlugin

def create_plugin(plugin_id: str, context: PluginContext) -> OcrOnnxPlugin:
    return OcrOnnxPlugin(plugin_id, context)

