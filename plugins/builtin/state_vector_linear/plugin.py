"""Linear state vector index plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.vector_index import LinearStateVectorIndex


def create_plugin(plugin_id: str, context: PluginContext) -> LinearStateVectorIndex:
    return LinearStateVectorIndex(plugin_id, context)
