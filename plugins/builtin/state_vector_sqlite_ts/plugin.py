"""SQLite-backed state vector index plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.vector_index_sqlite import SQLiteStateVectorIndex


def create_plugin(plugin_id: str, context: PluginContext) -> SQLiteStateVectorIndex:
    return SQLiteStateVectorIndex(plugin_id, context)
