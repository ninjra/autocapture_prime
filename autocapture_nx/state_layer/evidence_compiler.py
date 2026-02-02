"""Evidence compiler for state-layer query results."""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.processing.sst.compliance import redact_text

from .contracts import validate_query_bundle
from .policy_gate import StatePolicyDecision


class EvidenceCompiler(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._config = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}

    def capabilities(self) -> dict[str, Any]:
        return {"state.evidence_compiler": self}

    def compile(
        self,
        *,
        query_id: str,
        hits: list[dict[str, Any]],
        policy: StatePolicyDecision,
        metadata: Any,
    ) -> dict[str, Any]:
        cfg = self._config.get("evidence", {}) if isinstance(self._config.get("evidence", {}), dict) else {}
        max_hits = int(cfg.get("max_hits", 5) or 5)
        max_evidence = int(cfg.get("max_evidence_per_hit", 3) or 3)
        max_snippets = int(cfg.get("max_snippets_per_hit", 2) or 2)
        max_chars = int(cfg.get("max_snippet_chars", 280) or 280)

        compiled_hits: list[dict[str, Any]] = []
        for hit in hits[: max_hits]:
            evidence = _sorted_evidence(hit.get("evidence", []))[: max(0, max_evidence)]
            snippets: list[dict[str, Any]] = []
            if policy.can_export_text:
                snippets = _extract_snippets(
                    hit,
                    evidence,
                    metadata=metadata,
                    max_snippets=max_snippets,
                    max_chars=max_chars,
                    redact=policy.redact_text,
                )
            compiled_hits.append(
                {
                    "state_id": str(hit.get("state_id")),
                    "score": float(hit.get("score", 0.0)),
                    "ts_start_ms": int(hit.get("ts_start_ms", 0) or 0),
                    "ts_end_ms": int(hit.get("ts_end_ms", 0) or 0),
                    "evidence": evidence,
                    "extracted_text_snippets": snippets,
                }
            )

        bundle = {
            "query_id": str(query_id),
            "hits": compiled_hits,
            "policy": {
                "can_show_raw_media": bool(policy.can_show_raw_media),
                "can_export_text": bool(policy.can_export_text),
            },
        }
        validate_query_bundle(bundle)
        return bundle


def _sorted_evidence(evidence: Any) -> list[dict[str, Any]]:
    items = [e for e in evidence if isinstance(e, dict)]
    items.sort(key=lambda r: (int(r.get("ts_start_ms", 0)), str(r.get("media_id", ""))))
    return items


def _extract_snippets(
    hit: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    metadata: Any,
    max_snippets: int,
    max_chars: int,
    redact: bool,
) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    provenance = hit.get("provenance", {}) if isinstance(hit.get("provenance"), dict) else {}
    input_ids = provenance.get("input_artifact_ids", []) if isinstance(provenance.get("input_artifact_ids"), list) else []
    frame_map = _frame_state_map(input_ids, metadata)

    for ref in evidence:
        if len(snippets) >= max_snippets:
            break
        media_id = str(ref.get("media_id", ""))
        if not media_id:
            continue
        state_info = frame_map.get(media_id)
        if not state_info:
            continue
        text = _state_text_for(state_info, metadata)
        if not text:
            continue
        if redact:
            text, _count = redact_text(text, enabled=True)
        if max_chars > 0 and len(text) > max_chars:
            text = text[: max_chars].rstrip()
        snippets.append(
            {
                "media_id": media_id,
                "ts_ms": int(state_info.get("ts_ms", 0) or ref.get("ts_start_ms", 0) or 0),
                "text": text,
                "span": {"start": 0, "end": len(text)},
            }
        )
    return snippets


def _frame_state_map(input_ids: list[str], metadata: Any) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    if metadata is None:
        return mapping
    for record_id in input_ids:
        record = metadata.get(record_id, {})
        if not isinstance(record, dict):
            continue
        if str(record.get("record_type")) != "derived.sst.state":
            continue
        screen_state_raw = record.get("screen_state")
        screen_state = screen_state_raw if isinstance(screen_state_raw, dict) else {}
        frame_id = str(screen_state.get("frame_id") or record.get("frame_id") or "")
        if not frame_id:
            continue
        mapping[frame_id] = {
            "state_id": screen_state.get("state_id"),
            "run_id": record.get("run_id"),
            "ts_ms": screen_state.get("ts_ms"),
            "screen_state": screen_state,
        }
    return mapping


def _state_text_for(state_info: dict[str, Any], metadata: Any) -> str:
    run_id = state_info.get("run_id")
    state_id = state_info.get("state_id")
    if run_id and state_id and metadata is not None:
        component = encode_record_id_component(str(state_id))
        doc_id = f"{run_id}/derived.sst.text/state/{component}"
        doc = metadata.get(doc_id, {})
        if isinstance(doc, dict):
            text = str(doc.get("text", "")).strip()
            if text:
                return text
    screen_state_raw = state_info.get("screen_state")
    screen_state = screen_state_raw if isinstance(screen_state_raw, dict) else {}
    tokens_raw = screen_state.get("tokens")
    tokens = tokens_raw if isinstance(tokens_raw, (list, tuple)) else []
    parts = []
    for token in tokens:
        text = str(token.get("norm_text") or token.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()
