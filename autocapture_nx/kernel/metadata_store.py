"""Metadata store helpers with immutability guards."""

from __future__ import annotations

from typing import Any


def is_evidence_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type", ""))
    return record_type.startswith("evidence.")


def is_derived_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type", ""))
    return record_type.startswith("derived.")


class ImmutableMetadataStore:
    def __init__(self, store: Any) -> None:
        self._store = store

    def put(self, record_id: str, value: Any) -> None:
        existing = self._store.get(record_id)
        if isinstance(existing, dict) and is_evidence_record(existing):
            raise RuntimeError(f"Refusing to overwrite evidence record {record_id}")
        if isinstance(value, dict) and "record_type" not in value:
            raise ValueError(f"Metadata record {record_id} missing record_type")
        self._store.put(record_id, value)

    def put_new(self, record_id: str, value: Any) -> None:
        if isinstance(value, dict) and "record_type" not in value:
            raise ValueError(f"Metadata record {record_id} missing record_type")
        if hasattr(self._store, "put_new"):
            return self._store.put_new(record_id, value)
        existing = self._store.get(record_id)
        if existing is not None:
            raise FileExistsError(f"Metadata record already exists: {record_id}")
        self._store.put(record_id, value)

    def put_replace(self, record_id: str, value: Any) -> None:
        existing = self._store.get(record_id)
        if isinstance(existing, dict) and is_evidence_record(existing):
            raise RuntimeError(f"Refusing to overwrite evidence record {record_id}")
        if isinstance(value, dict) and is_evidence_record(value):
            raise RuntimeError(f"Refusing to overwrite evidence record {record_id}")
        if isinstance(value, dict) and "record_type" not in value:
            raise ValueError(f"Metadata record {record_id} missing record_type")
        if hasattr(self._store, "put_replace"):
            return self._store.put_replace(record_id, value)
        self._store.put(record_id, value)

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
