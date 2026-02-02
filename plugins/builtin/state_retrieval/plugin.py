"""State-layer retrieval plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.retrieval import StateRetrieval


def create_plugin(plugin_id: str, context: PluginContext) -> StateRetrieval:
    return StateRetrieval(plugin_id, context)
