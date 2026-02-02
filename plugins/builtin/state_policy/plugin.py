"""State-layer policy gate plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.policy_gate import StatePolicyGate


def create_plugin(plugin_id: str, context: PluginContext) -> StatePolicyGate:
    _ = plugin_id
    return StatePolicyGate(context.config if isinstance(context.config, dict) else {})
