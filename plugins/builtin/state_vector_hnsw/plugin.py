"""HNSW vector index plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.vector_index_hnsw import HNSWStateVectorIndex


def create_plugin(plugin_id: str, context: PluginContext) -> HNSWStateVectorIndex:
    return HNSWStateVectorIndex(plugin_id, context)
