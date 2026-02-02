"""JEPA-like state builder plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder


def create_plugin(plugin_id: str, context: PluginContext) -> JEPAStateBuilder:
    return JEPAStateBuilder(plugin_id, context)
