"""Workflow miner plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.workflow_miner import WorkflowMiner


def create_plugin(plugin_id: str, context: PluginContext) -> WorkflowMiner:
    return WorkflowMiner(plugin_id, context)
