"""Ledger transition requirements for evidence and derived records."""

from __future__ import annotations

from typing import Any, Iterable


def required_transitions(record_type: str) -> set[str]:
    if record_type == "evidence.capture.segment":
        return {"capture", "segment.seal"}
    if record_type == "evidence.window.meta":
        return {"window.meta"}
    if record_type in {"derived.text.ocr", "derived.text.vlm"}:
        return {"derived.extract"}
    if record_type == "derived.graph.edge":
        return {"derived.extract"}
    if record_type == "derived.input.summary":
        return {"input.batch"}
    if record_type == "derived.cursor.sample":
        return {"cursor.sample"}
    if record_type == "derived.audio.segment":
        return {"audio.capture"}
    if record_type == "derived.sst.frame":
        return {"sst.frame"}
    if record_type == "derived.sst.state":
        return {"sst.state"}
    if record_type == "derived.sst.text":
        return {"sst.text"}
    if record_type == "derived.sst.text.extra":
        return {"sst.extra_doc"}
    if record_type == "derived.sst.delta":
        return {"sst.delta"}
    if record_type == "derived.sst.action":
        return {"sst.action"}
    return set()


def missing_transitions(
    records: dict[str, dict[str, Any]],
    ledger_entries: Iterable[dict[str, Any]],
) -> dict[str, set[str]]:
    by_output: dict[str, set[str]] = {}
    for entry in ledger_entries:
        stage = entry.get("stage")
        if not stage:
            continue
        for output in entry.get("outputs", []) or []:
            by_output.setdefault(str(output), set()).add(str(stage))
    missing: dict[str, set[str]] = {}
    for record_id, record in records.items():
        record_type = str(record.get("record_type", ""))
        required = required_transitions(record_type)
        if not required:
            continue
        seen = by_output.get(str(record_id), set())
        gap = required - seen
        if gap:
            missing[str(record_id)] = gap
    return missing
