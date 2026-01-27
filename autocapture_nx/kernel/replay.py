"""Replay proof bundles without model calls."""

from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.citation_basic.plugin import CitationValidator


@dataclass(frozen=True)
class ReplayReport:
    ok: bool
    errors: list[str]
    warnings: list[str]
    citation_errors: list[dict[str, Any]]
    ledger_errors: list[str]
    index_errors: list[str]


def replay_bundle(path: str | Path) -> ReplayReport:
    path = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    citation_errors: list[dict[str, Any]] = []
    ledger_errors: list[str] = []
    index_errors: list[str] = []
    if not path.exists():
        return ReplayReport(
            ok=False,
            errors=[f"bundle_missing:{path}"],
            warnings=[],
            citation_errors=[],
            ledger_errors=[],
            index_errors=[],
        )
    with zipfile.ZipFile(path, "r") as zf:
        _read_json(zf, "manifest.json")
        metadata_lines = _read_text(zf, "metadata.jsonl").splitlines()
        ledger_text = _read_text(zf, "ledger.ndjson")
        anchor_text = _read_text(zf, "anchors.ndjson")
        citations = _read_json(zf, "citations.json", default=[])
    records = {}
    for line in metadata_lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            warnings.append("metadata_line_invalid")
            continue
        record_id = payload.get("record_id")
        record = payload.get("record")
        if record_id and isinstance(record, dict):
            records[str(record_id)] = record
    ledger_entries = []
    for line in ledger_text.splitlines():
        if not line.strip():
            continue
        try:
            ledger_entries.append(json.loads(line))
        except Exception:
            ledger_errors.append("ledger_line_invalid")
    if ledger_entries:
        ok_ledger, ledger_errors = _verify_ledger_entries(ledger_entries)
        if not ok_ledger:
            errors.extend(ledger_errors)
    else:
        errors.append("ledger_empty")
    index_errors.extend(_check_index_versions(ledger_entries))
    if index_errors:
        errors.extend(index_errors)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        ledger_path = tmp_root / "ledger.ndjson"
        anchor_path = tmp_root / "anchors.ndjson"
        ledger_path.write_text(ledger_text, encoding="utf-8")
        anchor_path.write_text(anchor_text, encoding="utf-8")
        metadata_store = _BundleStore(records)
        validator = CitationValidator(
            "citation.validator",
            PluginContext(
                config={"storage": {"data_dir": str(tmp_root), "anchor": {"path": str(anchor_path)}}},
                get_capability=lambda name: metadata_store if name == "storage.metadata" else None,
                logger=lambda _m: None,
            ),
        )
        if citations:
            result = validator.resolve(citations)
            if not result.get("ok"):
                citation_errors = result.get("errors", [])
                errors.append("citations_invalid")
        else:
            errors.append("citations_missing")

    ok = not errors
    return ReplayReport(
        ok=ok,
        errors=errors,
        warnings=warnings,
        citation_errors=citation_errors,
        ledger_errors=ledger_errors,
        index_errors=index_errors,
    )


class _BundleStore:
    def __init__(self, records: dict[str, dict[str, Any]]) -> None:
        self._records = dict(records)

    def get(self, record_id: str, default=None):
        return self._records.get(record_id, default)

    def keys(self) -> list[str]:
        return sorted(self._records.keys())


def _verify_ledger_entries(entries: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    prev = ""
    for entry in entries:
        entry_hash = entry.get("entry_hash")
        payload = dict(entry)
        payload.pop("entry_hash", None)
        canonical = dumps(payload)
        expected = sha256_text(canonical + (payload.get("prev_hash") or ""))
        if entry_hash != expected:
            errors.append("ledger_hash_mismatch")
        if prev and payload.get("prev_hash") != prev:
            errors.append("ledger_chain_gap")
        prev = entry_hash or prev
    return len(errors) == 0, errors


def _check_index_versions(entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        payload = entry.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("event") != "query.execute":
            continue
        trace = payload.get("retrieval_trace", [])
        if not isinstance(trace, list) or not trace:
            errors.append("retrieval_trace_missing")
            continue
        for step in trace:
            if not isinstance(step, dict):
                continue
            tier = step.get("tier")
            if tier not in {"LEXICAL", "VECTOR"}:
                continue
            index_meta = step.get("index")
            if not isinstance(index_meta, dict):
                errors.append("index_meta_missing")
                continue
            if index_meta.get("version") in (None, ""):
                errors.append("index_version_missing")
            if index_meta.get("digest") in (None, ""):
                errors.append("index_digest_missing")
    return errors


def _read_json(zf: zipfile.ZipFile, name: str, default: Any | None = None) -> Any:
    try:
        return json.loads(zf.read(name))
    except Exception:
        return default


def _read_text(zf: zipfile.ZipFile, name: str) -> str:
    try:
        return zf.read(name).decode("utf-8")
    except Exception:
        return ""
