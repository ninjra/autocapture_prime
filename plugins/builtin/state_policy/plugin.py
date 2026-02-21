"""State-layer policy gate plugin."""

from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.state_layer.policy_gate import StatePolicyGate


class StatePolicyPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._gate = StatePolicyGate(context.config if isinstance(context.config, dict) else {})

    def capabilities(self) -> dict[str, object]:
        return {"state.policy": self}

    def decide(self, query_context: dict | None = None) -> object:
        return self._gate.decide(query_context)

    def app_allowed(self, app_hint: str | None, decision: object | None = None) -> bool:
        return self._gate.app_allowed(app_hint, decision)


def create_plugin(plugin_id: str, context: PluginContext) -> StatePolicyPlugin:
    return StatePolicyPlugin(plugin_id, context)
