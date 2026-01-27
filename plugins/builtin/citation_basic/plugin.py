"""Citation validator plugin."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CitationValidator(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"citation.validator": self}

    def validate(self, citations: list[dict[str, Any]]) -> bool:
        metadata = None
        try:
            metadata = self.context.get_capability("storage.metadata")
        except Exception:
            metadata = None
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError("Citation must be a dict")
            for field in ("span_id", "source", "offset_start", "offset_end"):
                if field not in citation:
                    raise ValueError(f"Missing citation field: {field}")
            if metadata is not None:
                record_id = citation.get("span_id")
                record = metadata.get(record_id)
                if not isinstance(record, dict):
                    raise ValueError(f"Citation span_id not found: {record_id}")
                record_type = str(record.get("record_type", ""))
                if not record_type.startswith("evidence."):
                    raise ValueError(f"Citation span_id not evidence: {record_id}")
        return True


def create_plugin(plugin_id: str, context: PluginContext) -> CitationValidator:
    return CitationValidator(plugin_id, context)
