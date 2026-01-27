"""Citation validator plugin."""

from __future__ import annotations

from typing import Any

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.metadata_store import is_derived_record, is_evidence_record
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CitationValidator(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"citation.validator": self}

    def resolve(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        metadata = self._metadata()
        errors: list[dict[str, Any]] = []
        resolved: list[dict[str, Any]] = []
        if metadata is None:
            return {
                "ok": False,
                "resolved": [],
                "errors": [{"error": "missing_metadata"}],
            }
        for idx, citation in enumerate(citations):
            ctx = {"index": idx}
            if not isinstance(citation, dict):
                errors.append({**ctx, "error": "citation_not_dict"})
                continue
            evidence_id = citation.get("evidence_id") or citation.get("span_id")
            if not evidence_id:
                errors.append({**ctx, "error": "missing_evidence_id"})
                continue
            span_id = citation.get("span_id") or evidence_id
            derived_id = citation.get("derived_id")
            if span_id not in {evidence_id, derived_id}:
                errors.append({**ctx, "error": "span_id_mismatch", "span_id": span_id})
                continue
            source = citation.get("source")
            if source is None:
                errors.append({**ctx, "error": "missing_source"})
                continue
            try:
                offset_start = int(citation.get("offset_start"))
                offset_end = int(citation.get("offset_end"))
            except Exception:
                errors.append({**ctx, "error": "invalid_offsets"})
                continue
            if offset_start < 0 or offset_end < offset_start:
                errors.append({**ctx, "error": "invalid_offsets"})
                continue
            evidence_record = metadata.get(evidence_id)
            if not isinstance(evidence_record, dict):
                errors.append({**ctx, "error": "evidence_not_found", "evidence_id": evidence_id})
                continue
            if not is_evidence_record(evidence_record):
                errors.append({**ctx, "error": "evidence_wrong_type", "evidence_id": evidence_id})
                continue
            evidence_hash = citation.get("evidence_hash")
            expected_evidence_hash = _record_hash(evidence_record)
            if not evidence_hash:
                errors.append({**ctx, "error": "missing_evidence_hash", "evidence_id": evidence_id})
                continue
            if expected_evidence_hash and str(evidence_hash) != expected_evidence_hash:
                errors.append({**ctx, "error": "evidence_hash_mismatch", "evidence_id": evidence_id})
                continue
            if derived_id:
                derived_record = metadata.get(derived_id)
                if not isinstance(derived_record, dict):
                    errors.append({**ctx, "error": "derived_not_found", "derived_id": derived_id})
                    continue
                if not is_derived_record(derived_record):
                    errors.append({**ctx, "error": "derived_wrong_type", "derived_id": derived_id})
                    continue
                source_id = derived_record.get("source_id")
                if source_id and source_id != evidence_id:
                    errors.append({**ctx, "error": "derived_source_mismatch", "derived_id": derived_id})
                    continue
                derived_hash = citation.get("derived_hash")
                expected_derived_hash = _record_hash(derived_record)
                if not derived_hash:
                    errors.append({**ctx, "error": "missing_derived_hash", "derived_id": derived_id})
                    continue
                if expected_derived_hash and str(derived_hash) != expected_derived_hash:
                    errors.append({**ctx, "error": "derived_hash_mismatch", "derived_id": derived_id})
                    continue
            resolved.append(
                {
                    "span_id": span_id,
                    "evidence_id": evidence_id,
                    "evidence_hash": evidence_hash,
                    "derived_id": derived_id,
                    "derived_hash": citation.get("derived_hash") if derived_id else None,
                    "source": source,
                    "offset_start": offset_start,
                    "offset_end": offset_end,
                }
            )
        return {"ok": not errors, "resolved": resolved, "errors": errors}

    def validate(self, citations: list[dict[str, Any]]) -> bool:
        result = self.resolve(citations)
        if not result.get("ok"):
            first_error = result.get("errors", [{}])[0]
            raise ValueError(f"Citation validation failed: {first_error}")
        return True

    def _metadata(self):
        try:
            return self.context.get_capability("storage.metadata")
        except Exception:
            return None


def create_plugin(plugin_id: str, context: PluginContext) -> CitationValidator:
    return CitationValidator(plugin_id, context)


def _record_hash(record: dict[str, Any]) -> str | None:
    if not isinstance(record, dict):
        return None
    content_hash = record.get("content_hash")
    if content_hash:
        return str(content_hash)
    text = record.get("text")
    if text:
        return hash_text(normalize_text(str(text)))
    return None
