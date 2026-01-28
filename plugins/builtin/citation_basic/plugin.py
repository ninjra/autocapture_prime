"""Citation validator plugin."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from typing import Any

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.kernel.metadata_store import is_derived_record, is_evidence_record
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CitationValidator(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._ledger_cache: dict[str, Any] | None = None

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
            span_kind = citation.get("span_kind")
            if not span_kind:
                errors.append({**ctx, "error": "missing_span_kind"})
                continue
            schema_version = citation.get("schema_version")
            if schema_version is None:
                errors.append({**ctx, "error": "missing_schema_version"})
                continue
            try:
                schema_version = int(schema_version)
            except Exception:
                errors.append({**ctx, "error": "invalid_schema_version"})
                continue
            ledger_head = citation.get("ledger_head")
            if not ledger_head:
                errors.append({**ctx, "error": "missing_ledger_head"})
                continue
            anchor_ref = citation.get("anchor_ref")
            if not anchor_ref:
                errors.append({**ctx, "error": "missing_anchor_ref"})
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
            derived_record = None
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
            span_ref = citation.get("span_ref")
            if span_ref is not None:
                if not isinstance(span_ref, dict):
                    errors.append({**ctx, "error": "span_ref_invalid"})
                    continue
                target_record = derived_record if derived_id else evidence_record
                expected_span = None
                if isinstance(target_record, dict):
                    expected_span = target_record.get("span_ref")
                if expected_span:
                    mismatch = False
                    for key, value in span_ref.items():
                        if expected_span.get(key) != value:
                            mismatch = True
                            break
                    if mismatch:
                        errors.append({**ctx, "error": "span_ref_mismatch"})
                        continue
                else:
                    if span_ref.get("kind") == "time":
                        if not _span_within_record(target_record, span_ref):
                            errors.append({**ctx, "error": "span_ref_out_of_bounds"})
                            continue
                    else:
                        errors.append({**ctx, "error": "span_ref_missing"})
                        continue
                span_source = span_ref.get("source_id")
                if span_source and span_source != evidence_id:
                    errors.append({**ctx, "error": "span_source_mismatch"})
                    continue
            if span_kind == "text":
                source_record = derived_record if derived_id else evidence_record
                source_text = str(source_record.get("text", "")) if isinstance(source_record, dict) else ""
                if not source_text:
                    errors.append({**ctx, "error": "missing_text_for_span"})
                    continue
                if offset_end > len(source_text):
                    errors.append({**ctx, "error": "span_out_of_bounds"})
                    continue
            if not self._verify_ledger(str(ledger_head)):
                errors.append({**ctx, "error": "ledger_head_invalid"})
                continue
            if not self._verify_anchor(anchor_ref):
                errors.append({**ctx, "error": "anchor_invalid"})
                continue
            resolved.append(
                {
                    "schema_version": schema_version,
                    "span_id": span_id,
                    "evidence_id": evidence_id,
                    "evidence_hash": evidence_hash,
                    "derived_id": derived_id,
                    "derived_hash": citation.get("derived_hash") if derived_id else None,
                    "span_kind": span_kind,
                    "span_ref": citation.get("span_ref"),
                    "ledger_head": ledger_head,
                    "anchor_ref": anchor_ref,
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

    def _ledger_path(self) -> str:
        storage_cfg = self.context.config.get("storage", {}) if isinstance(self.context.config, dict) else {}
        data_dir = storage_cfg.get("data_dir", "data")
        return os.path.join(data_dir, "ledger.ndjson")

    def _anchor_path(self) -> str:
        storage_cfg = self.context.config.get("storage", {}) if isinstance(self.context.config, dict) else {}
        anchor_cfg = storage_cfg.get("anchor", {}) if isinstance(storage_cfg, dict) else {}
        return anchor_cfg.get("path", os.path.join("data_anchor", "anchors.ndjson"))

    def _verify_ledger(self, expected_head: str) -> bool:
        path = self._ledger_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return False
        cache = self._ledger_cache
        if cache and cache.get("mtime") == mtime:
            return cache.get("head") == expected_head and cache.get("ok", False)
        head = None
        ok = True
        try:
            with open(path, "r", encoding="utf-8") as handle:
                prev = ""
                for line in handle:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    entry_hash = entry.get("entry_hash")
                    payload = dict(entry)
                    payload.pop("entry_hash", None)
                    canonical = dumps(payload)
                    computed = sha256_text(canonical + prev)
                    if entry_hash != computed:
                        ok = False
                        break
                    prev = entry_hash or ""
                head = prev or None
        except Exception:
            ok = False
        self._ledger_cache = {"mtime": mtime, "head": head, "ok": ok}
        return ok and head == expected_head

    def _verify_anchor(self, anchor_ref: Any) -> bool:
        if not isinstance(anchor_ref, dict):
            return False
        anchor_path = self._anchor_path()
        try:
            with open(anchor_path, "r", encoding="utf-8") as handle:
                lines = [line.strip() for line in handle if line.strip()]
        except Exception:
            return False
        anchor_seq = anchor_ref.get("anchor_seq")
        ledger_head_hash = anchor_ref.get("ledger_head_hash")
        if anchor_seq is None or ledger_head_hash is None:
            return False
        for line in lines:
            record = _decode_anchor_line(line)
            if not isinstance(record, dict):
                continue
            if record.get("anchor_seq") != anchor_seq:
                continue
            if record.get("ledger_head_hash") != ledger_head_hash:
                return False
            if "anchor_hmac" in record:
                if not self._verify_anchor_hmac(record):
                    return False
            return True
        return False

    def _verify_anchor_hmac(self, record: dict[str, Any]) -> bool:
        keyring = None
        try:
            keyring = self.context.get_capability("storage.keyring")
        except Exception:
            keyring = None
        if not isinstance(keyring, KeyRing):
            return False
        key_id = record.get("anchor_key_id")
        anchor_hmac = record.get("anchor_hmac")
        if not key_id or not anchor_hmac:
            return False
        try:
            root = keyring.key_for(str(key_id))
        except Exception:
            return False
        from autocapture_nx.kernel.crypto import derive_key
        import hmac
        import hashlib

        key = derive_key(root, "anchor")
        payload = dict(record)
        payload.pop("anchor_hmac", None)
        payload_bytes = dumps(payload).encode("utf-8")
        expected = hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()
        return expected == anchor_hmac


def create_plugin(plugin_id: str, context: PluginContext) -> CitationValidator:
    return CitationValidator(plugin_id, context)


def _record_hash(record: dict[str, Any]) -> str | None:
    if not isinstance(record, dict):
        return None
    content_hash = record.get("content_hash")
    if content_hash:
        return str(content_hash)
    payload_hash = record.get("payload_hash")
    if payload_hash:
        return str(payload_hash)
    text = record.get("text")
    if text:
        return hash_text(normalize_text(str(text)))
    return None


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _span_within_record(record: dict[str, Any] | None, span_ref: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    start_ts = _parse_ts(span_ref.get("start_ts_utc"))
    end_ts = _parse_ts(span_ref.get("end_ts_utc"))
    rec_start = _parse_ts(record.get("ts_start_utc") or record.get("ts_utc"))
    rec_end = _parse_ts(record.get("ts_end_utc") or record.get("ts_utc"))
    if rec_start is None:
        return False
    if rec_end is None:
        rec_end = rec_start
    if start_ts and start_ts < rec_start:
        return False
    if end_ts and end_ts > rec_end:
        return False
    return True


def _decode_anchor_line(line: str) -> dict[str, Any] | None:
    if line.startswith("DPAPI:"):
        data = line.split("DPAPI:", 1)[1]
        try:
            raw = base64.b64decode(data)
            from autocapture_nx.windows.dpapi import unprotect

            decoded = unprotect(raw)
            return json.loads(decoded.decode("utf-8"))
        except Exception:
            return None
    try:
        return json.loads(line)
    except Exception:
        return None
