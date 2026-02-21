"""Citable ledger utilities."""

from __future__ import annotations

import json
import hashlib
import base64
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture.core.hashing import canonical_dumps
from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps_nx
from autocapture_nx.kernel.keyring import KeyRing


@dataclass
class LedgerEntry:
    payload: dict[str, Any]
    entry_hash: str


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash: str | None = None
        if self.path.exists():
            self._last_hash = self._scan_last_hash()

    def _scan_last_hash(self) -> str | None:
        last = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                last = entry.get("entry_hash", last)
        return last

    def append(self, entry: dict[str, Any]) -> str:
        required = {
            "record_type",
            "schema_version",
            "entry_id",
            "ts_utc",
            "stage",
            "inputs",
            "outputs",
            "policy_snapshot_hash",
        }
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"Ledger entry missing fields: {sorted(missing)}")
        payload = dict(entry)
        prev_hash = self._last_hash
        payload["prev_hash"] = prev_hash
        payload.pop("entry_hash", None)
        canonical = canonical_dumps(payload)
        entry_hash = hashlib.sha256((canonical + (prev_hash or "")).encode("utf-8")).hexdigest()
        payload["entry_hash"] = entry_hash
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        self._last_hash = entry_hash
        return entry_hash


def verify_ledger(path: str | Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    prev_hash: str | None = None
    with Path(path).open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if not line.strip():
                continue
            entry = json.loads(line)
            entry_hash = entry.get("entry_hash")
            payload = dict(entry)
            payload.pop("entry_hash", None)
            canonical = canonical_dumps(payload)
            expected = hashlib.sha256((canonical + (prev_hash or "")).encode("utf-8")).hexdigest()
            if entry_hash != expected:
                errors.append(f"hash_mismatch:{idx}")
            prev_hash = entry_hash
    return len(errors) == 0, errors


def verify_anchors(path: str | Path, keyring: KeyRing | None = None) -> tuple[bool, list[str]]:
    errors: list[str] = []
    anchor_path = Path(path)
    if not anchor_path.exists():
        return False, ["anchor_missing"]
    try:
        for line in anchor_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = _decode_anchor_line(line)
            if not isinstance(record, dict):
                errors.append("anchor_decode_failed")
                continue
            if "anchor_seq" not in record or "ledger_head_hash" not in record:
                errors.append("anchor_missing_fields")
                continue
            if "anchor_hmac" in record:
                if keyring is None:
                    errors.append("anchor_keyring_missing")
                    continue
                key_id = record.get("anchor_key_id")
                if not key_id:
                    errors.append("anchor_key_id_missing")
                    continue
                try:
                    root = keyring.key_for("anchor", str(key_id))
                except Exception:
                    errors.append("anchor_key_missing")
                    continue
                payload = dict(record)
                payload.pop("anchor_hmac", None)
                payload.pop("anchor_key_id", None)
                payload_bytes = canonical_dumps_nx(payload).encode("utf-8")
                key = derive_key(root, "anchor")
                expected = hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()
                if expected != record.get("anchor_hmac"):
                    errors.append("anchor_hmac_mismatch")
    except Exception:
        errors.append("anchor_read_failed")
    return len(errors) == 0, errors


def verify_evidence(metadata: Any, media: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if metadata is None:
        return False, ["metadata_missing"]
    if media is None:
        return False, ["media_missing"]
    try:
        record_ids = metadata.keys()
    except Exception:
        return False, ["metadata_keys_failed"]
    for record_id in record_ids:
        try:
            record = metadata.get(record_id)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("record_type") or "")
        # Only evidence records require a corresponding media blob.
        if not record_type.startswith("evidence."):
            continue
        payload_hash = record.get("payload_hash")
        if payload_hash:
            expected = sha256_canonical({k: v for k, v in record.items() if k != "payload_hash"})
            if str(payload_hash) != expected:
                errors.append(f"payload_hash_mismatch:{record_id}")
        content_hash = record.get("content_hash")
        if content_hash:
            media_id = record.get("source_id") or record.get("artifact_id") or record_id
            try:
                data = media.get(media_id)
            except Exception:
                data = None
            if not data:
                errors.append(f"evidence_missing:{media_id}")
                continue
            actual = hashlib.sha256(data).hexdigest()
            if str(content_hash) != actual:
                errors.append(f"content_hash_mismatch:{media_id}")
    return len(errors) == 0, errors


def verify_metadata_refs(metadata: Any) -> tuple[bool, list[str]]:
    """Verify internal reference integrity inside the metadata store.

    This is intentionally conservative and lightweight:
    - derived records that declare `source_id` must reference an existing evidence-like record
    - optional `parent_evidence_id` must reference an existing evidence-like record
    - optional `span_ref.source_id` must reference the evidence-like record
    """
    errors: list[str] = []
    if metadata is None:
        return False, ["metadata_missing"]
    try:
        record_ids = metadata.keys()
    except Exception:
        return False, ["metadata_keys_failed"]

    # Preload evidence ids for O(1) checks.
    evidence_like: set[str] = set()
    for record_id in record_ids:
        try:
            record = metadata.get(record_id)
        except Exception:
            continue
        if isinstance(record, dict):
            record_type = str(record.get("record_type") or "")
            if record_type.startswith("evidence."):
                evidence_like.add(str(record_id))

    for record_id in record_ids:
        try:
            record = metadata.get(record_id)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        if source_id is not None:
            if str(source_id) not in evidence_like:
                errors.append(f"source_id_missing:{record_id}")
        parent_id = record.get("parent_evidence_id")
        if parent_id is not None:
            if str(parent_id) not in evidence_like:
                errors.append(f"parent_evidence_id_missing:{record_id}")
        span_ref = record.get("span_ref")
        if isinstance(span_ref, dict):
            span_source = span_ref.get("source_id")
            if span_source is not None and str(span_source) not in evidence_like:
                errors.append(f"span_ref_source_missing:{record_id}")

    return len(errors) == 0, errors


def integrity_scan(
    *,
    ledger_path: str | Path,
    anchor_path: str | Path,
    metadata: Any,
    media: Any,
    keyring: KeyRing | None = None,
) -> dict[str, Any]:
    """Full integrity scan used by gates and operator tooling."""
    ledger_ok, ledger_errors = verify_ledger(ledger_path)
    anchors_ok, anchors_errors = verify_anchors(anchor_path, keyring)
    evidence_ok, evidence_errors = verify_evidence(metadata, media)
    refs_ok, refs_errors = verify_metadata_refs(metadata)

    checks = [
        {"name": "ledger", "ok": ledger_ok, "errors": ledger_errors, "path": str(ledger_path)},
        {"name": "anchors", "ok": anchors_ok, "errors": anchors_errors, "path": str(anchor_path)},
        {"name": "evidence", "ok": evidence_ok, "errors": evidence_errors},
        {"name": "metadata_refs", "ok": refs_ok, "errors": refs_errors},
    ]
    ok = bool(ledger_ok and anchors_ok and evidence_ok and refs_ok)
    return {"ok": ok, "checks": checks}


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
