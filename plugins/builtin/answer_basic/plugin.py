"""Answer builder plugin with claim-level citations."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class AnswerBuilder(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"answer.builder": self}

    def build(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        validator = self.context.get_capability("citation.validator")
        for claim in claims:
            if "text" not in claim:
                raise ValueError("Claim missing text")
            citations = claim.get("citations", [])
            validator.validate(citations)
        return {"claims": claims}


def create_plugin(plugin_id: str, context: PluginContext) -> AnswerBuilder:
    return AnswerBuilder(plugin_id, context)
