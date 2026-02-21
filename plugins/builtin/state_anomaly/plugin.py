"""Anomaly detector plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.anomaly import AnomalyDetector


def create_plugin(plugin_id: str, context: PluginContext) -> AnomalyDetector:
    return AnomalyDetector(plugin_id, context)
