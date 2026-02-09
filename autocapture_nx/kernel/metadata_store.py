"""Metadata store helpers with immutability guards."""

from __future__ import annotations

import time
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import prefixed_id

from autocapture_nx.kernel.evidence import validate_evidence_record, is_evidence_like


def is_evidence_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type", ""))
    return record_type.startswith("evidence.")


def is_derived_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type", ""))
    return record_type.startswith("derived.")


def _validate_record(value: dict[str, Any], record_id: str) -> None:
    record_type = str(value.get("record_type", ""))
    if not record_type:
        raise ValueError(f"Metadata record {record_id} missing record_type")
    if is_evidence_like(value):
        validate_evidence_record(value, record_id)


class ImmutableMetadataStore:
    def __init__(self, store: Any) -> None:
        self._store = store

    def put(self, record_id: str, value: Any) -> None:
        existing = self._store.get(record_id)
        if isinstance(existing, dict) and (is_evidence_record(existing) or is_derived_record(existing)):
            raise RuntimeError(f"Refusing to overwrite immutable record {record_id}")
        if isinstance(value, dict):
            _validate_record(value, record_id)
        if isinstance(value, dict) and existing is not None and is_derived_record(value):
            raise RuntimeError(f"Refusing to overwrite immutable record {record_id}")
        self._store.put(record_id, value)

    def put_new(self, record_id: str, value: Any) -> None:
        if isinstance(value, dict):
            _validate_record(value, record_id)
        if hasattr(self._store, "put_new"):
            return self._store.put_new(record_id, value)
        existing = self._store.get(record_id)
        if existing is not None:
            raise FileExistsError(f"Metadata record already exists: {record_id}")
        self._store.put(record_id, value)

    def put_replace(self, record_id: str, value: Any) -> None:
        existing = self._store.get(record_id)
        if isinstance(existing, dict) and (is_evidence_record(existing) or is_derived_record(existing)):
            raise RuntimeError(f"Refusing to overwrite immutable record {record_id}")
        if isinstance(value, dict) and (is_evidence_record(value) or is_derived_record(value)):
            raise RuntimeError(f"Refusing to overwrite immutable record {record_id}")
        if isinstance(value, dict):
            _validate_record(value, record_id)
        if hasattr(self._store, "put_replace"):
            return self._store.put_replace(record_id, value)
        self._store.put(record_id, value)

    def put_batch(self, records: list[tuple[str, dict[str, Any]]]) -> list[str]:
        if not records:
            return []
        candidates: list[tuple[str, dict[str, Any]]] = []
        for record_id, payload in records:
            existing = self._store.get(record_id)
            if isinstance(existing, dict) and (is_evidence_record(existing) or is_derived_record(existing)):
                continue
            if isinstance(payload, dict):
                _validate_record(payload, record_id)
                if existing is not None and is_derived_record(payload):
                    continue
            if existing is None:
                candidates.append((record_id, payload))
        if not candidates:
            return []
        if hasattr(self._store, "put_batch"):
            try:
                batch_result = self._store.put_batch(candidates)
                return list(batch_result) if batch_result is not None else [rid for rid, _ in candidates]
            except Exception:
                pass
        inserted: list[str] = []
        for record_id, payload in candidates:
            try:
                if hasattr(self._store, "put_new"):
                    self._store.put_new(record_id, payload)
                else:
                    self._store.put(record_id, payload)
            except Exception:
                continue
            inserted.append(record_id)
        return inserted

    def delete(self, record_id: str) -> bool:
        existing = self._store.get(record_id)
        if existing is None:
            return False
        if isinstance(existing, dict) and not is_derived_record(existing):
            raise RuntimeError(f"Refusing to delete non-derived record {record_id}")
        if hasattr(self._store, "delete"):
            return bool(self._store.delete(record_id))
        raise RuntimeError("Underlying store does not support delete")

    def get(self, record_id: str, default: Any = None) -> Any:
        return self._store.get(record_id, default)

    def keys(self) -> list[str]:
        return self._store.keys()

    def rotate(self, *args, **kwargs):
        if hasattr(self._store, "rotate"):
            return self._store.rotate(*args, **kwargs)
        return 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def build_unavailable_record(
    run_id: str,
    *,
    ts_utc: str,
    reason: str,
    parent_evidence_id: str | None = None,
    source_record_type: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "evidence.capture.unavailable",
        "run_id": run_id,
        "ts_utc": ts_utc,
        "reason": reason,
    }
    if parent_evidence_id:
        payload["parent_evidence_id"] = parent_evidence_id
    if source_record_type:
        payload["source_record_type"] = source_record_type
    if details:
        payload.update(details)
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return payload


def persist_unavailable_record(
    metadata: Any,
    run_id: str,
    *,
    ts_utc: str,
    reason: str,
    parent_evidence_id: str | None = None,
    source_record_type: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    record_id = prefixed_id(run_id, "capture.unavailable", int(time.time() * 1000))
    payload = build_unavailable_record(
        run_id,
        ts_utc=ts_utc,
        reason=reason,
        parent_evidence_id=parent_evidence_id,
        source_record_type=source_record_type,
        details=details,
    )
    if hasattr(metadata, "put_new"):
        metadata.put_new(record_id, payload)
    else:
        metadata.put(record_id, payload)
    return record_id
