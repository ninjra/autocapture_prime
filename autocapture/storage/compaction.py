"""Derived-only storage compaction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CompactionResult:
    derived_metadata: int
    derived_media: int
    removed_index_files: int
    freed_bytes: int
    dry_run: bool


def _is_derived_id(record_id: str) -> bool:
    token = record_id.lower()
    return token.startswith("derived.") or "/derived." in token or "/derived/" in token


def _is_derived_record(record_id: str, record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type", ""))
    if record_type.startswith("derived."):
        return True
    return _is_derived_id(record_id)


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def compact_derived(
    metadata: Any,
    media: Any,
    config: dict[str, Any],
    *,
    dry_run: bool = False,
    event_builder: Any | None = None,
) -> CompactionResult:
    storage_cfg = config.get("storage", {})
    data_dir = Path(storage_cfg.get("data_dir", "data"))
    metadata_path = Path(storage_cfg.get("metadata_path", data_dir / "metadata"))
    lexical_path = Path(storage_cfg.get("lexical_path", data_dir / "lexical.db"))
    vector_path = Path(storage_cfg.get("vector_path", data_dir / "vector.db"))

    before_meta_bytes = _path_size(metadata_path)
    before_index_bytes = _path_size(lexical_path) + _path_size(vector_path)

    derived_meta_ids: list[str] = []
    for record_id in getattr(metadata, "keys", lambda: [])():
        record = metadata.get(record_id, {})
        if isinstance(record, dict) and _is_derived_record(record_id, record):
            derived_meta_ids.append(record_id)

    derived_media_ids: list[str] = []
    for record_id in getattr(media, "keys", lambda: [])():
        if _is_derived_id(record_id):
            derived_media_ids.append(record_id)

    if not dry_run:
        for record_id in derived_meta_ids:
            try:
                metadata.delete(record_id)
            except Exception:
                continue
        for record_id in derived_media_ids:
            try:
                media.delete(record_id)
            except Exception:
                continue

        store = getattr(metadata, "_store", None)
        if store is not None and hasattr(store, "vacuum"):
            try:
                store.vacuum()
            except Exception:
                pass

        removed_index_files = 0
        for path in (lexical_path, vector_path):
            if path.exists():
                try:
                    path.unlink()
                    removed_index_files += 1
                except OSError:
                    continue
    else:
        removed_index_files = int(lexical_path.exists()) + int(vector_path.exists())

    after_meta_bytes = _path_size(metadata_path) if not dry_run else before_meta_bytes
    after_index_bytes = _path_size(lexical_path) + _path_size(vector_path) if not dry_run else before_index_bytes
    freed_bytes = max(0, (before_meta_bytes + before_index_bytes) - (after_meta_bytes + after_index_bytes))

    result = CompactionResult(
        derived_metadata=len(derived_meta_ids),
        derived_media=len(derived_media_ids),
        removed_index_files=removed_index_files,
        freed_bytes=freed_bytes,
        dry_run=dry_run,
    )

    if event_builder is not None:
        payload = json.loads(json.dumps(result.__dict__))
        payload["event"] = "storage.compact_derived"
        payload["ts_utc"] = datetime.now(timezone.utc).isoformat()
        try:
            event_builder.journal_event("storage.compact_derived", payload, ts_utc=payload["ts_utc"])
            event_builder.ledger_entry(
                "storage.compact_derived",
                inputs=[],
                outputs=[],
                payload=payload,
                ts_utc=payload["ts_utc"],
            )
        except Exception:
            pass

    return result
