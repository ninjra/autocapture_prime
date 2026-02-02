"""JEPA training plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.jepa_training import JEPATraining


def create_plugin(plugin_id: str, context: PluginContext) -> JEPATraining:
    return JEPATraining(plugin_id, context)
