"""State-layer evidence compiler plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.evidence_compiler import EvidenceCompiler


def create_plugin(plugin_id: str, context: PluginContext) -> EvidenceCompiler:
    return EvidenceCompiler(plugin_id, context)
