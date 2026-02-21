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
        errors: list[dict[str, Any]] = []
        valid_claims: list[dict[str, Any]] = []
        for idx, claim in enumerate(claims):
            ctx = {"index": idx}
            if not isinstance(claim, dict):
                errors.append({**ctx, "error": "claim_not_dict"})
                continue
            text = claim.get("text")
            if not text:
                errors.append({**ctx, "error": "missing_text"})
                continue
            citations = claim.get("citations", [])
            if not citations:
                errors.append({**ctx, "error": "missing_citations"})
                continue
            try:
                resolved = validator.resolve(citations) if hasattr(validator, "resolve") else {"ok": True, "resolved": citations, "errors": []}
            except Exception as exc:
                errors.append({**ctx, "error": "citation_error", "detail": str(exc)})
                continue
            if not resolved.get("ok"):
                errors.append({**ctx, "error": "citation_invalid", "detail": resolved.get("errors", [])})
                continue
            valid_claims.append({"text": text, "citations": resolved.get("resolved", citations)})
        if not valid_claims:
            state = "no_evidence"
        elif errors:
            state = "partial"
        else:
            state = "ok"
        return {"state": state, "claims": valid_claims, "errors": errors}


def create_plugin(plugin_id: str, context: PluginContext) -> AnswerBuilder:
    return AnswerBuilder(plugin_id, context)
