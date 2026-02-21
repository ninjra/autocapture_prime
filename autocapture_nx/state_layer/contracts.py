"""Schema validation for state layer contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.paths import resolve_repo_path


_validator = SchemaLiteValidator()


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    path = resolve_repo_path("contracts/state_layer.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _subschema(name: str) -> dict[str, Any]:
    schema = _schema()
    block = schema.get("properties", {}).get(name)
    if not isinstance(block, dict):
        raise ValueError(f"State layer schema missing {name}")
    return block


def validate_evidence_ref(ref: dict[str, Any]) -> None:
    _validator.validate(_subschema("EvidenceRef"), ref)


def validate_provenance(record: dict[str, Any]) -> None:
    _validator.validate(_subschema("ProvenanceRecord"), record)


def _require_evidence_and_provenance(obj: dict[str, Any], *, label: str) -> None:
    evidence = obj.get("evidence")
    provenance = obj.get("provenance")
    if not evidence or not isinstance(evidence, list):
        raise ValueError(f"{label} missing EvidenceRef[]")
    if not provenance or not isinstance(provenance, dict):
        raise ValueError(f"{label} missing ProvenanceRecord")


def validate_state_span(span: dict[str, Any]) -> None:
    _validator.validate(_subschema("StateSpan"), span)
    _require_evidence_and_provenance(span, label="StateSpan")
    for ref in span.get("evidence", []):
        if isinstance(ref, dict):
            validate_evidence_ref(ref)
    if isinstance(span.get("provenance"), dict):
        validate_provenance(span["provenance"])


def validate_state_edge(edge: dict[str, Any]) -> None:
    _validator.validate(_subschema("StateEdge"), edge)
    _require_evidence_and_provenance(edge, label="StateEdge")
    for ref in edge.get("evidence", []):
        if isinstance(ref, dict):
            validate_evidence_ref(ref)
    if isinstance(edge.get("provenance"), dict):
        validate_provenance(edge["provenance"])


def validate_query_bundle(bundle: dict[str, Any]) -> None:
    _validator.validate(_subschema("QueryEvidenceBundle"), bundle)
    hits = bundle.get("hits", [])
    if not isinstance(hits, list):
        return
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        evidence = hit.get("evidence", [])
        for ref in evidence:
            if isinstance(ref, dict):
                validate_evidence_ref(ref)
