"""File ingest with content-addressed IDs and dedupe (FND-05)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, BinaryIO

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.prefixed_id import input_id_from_sha256


def _sha256_stream(handle: BinaryIO, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            break
        size += len(chunk)
        h.update(chunk)
    return h.hexdigest(), size


def _media_record_id(sha256_hex: str) -> str:
    return f"media/sha256/{sha256_hex}"


@dataclass(frozen=True)
class IngestResult:
    input_id: str
    media_record_id: str
    sha256: str
    size_bytes: int
    deduped: bool


def ingest_file(
    *,
    path: str,
    storage_media: Any,
    storage_meta: Any,
    ts_utc: str,
    run_id: str,
    event_builder: Any | None = None,
    fsync_policy: str | None = None,
) -> IngestResult:
    """Ingest a local file into (media, metadata) with dedupe.

    This is intentionally raw-first: the media blob is stored as-is; sanitization
    must only happen on explicit export paths.
    """

    file_path = str(path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    with open(file_path, "rb") as handle:
        sha256_hex, size_bytes = _sha256_stream(handle)

    input_id = input_id_from_sha256(sha256_hex)
    media_record_id = _media_record_id(sha256_hex)

    existed = False
    try:
        existed = bool(getattr(storage_media, "exists")(media_record_id))
    except Exception:
        existed = False

    if not existed:
        # Stream the file into media store (avoid large peak memory).
        with open(file_path, "rb") as handle:
            if hasattr(storage_media, "put_stream"):
                storage_media.put_stream(media_record_id, handle, ts_utc=ts_utc)
            else:
                blob = handle.read()
                try:
                    storage_media.put_new(media_record_id, blob, ts_utc=ts_utc, fsync_policy=fsync_policy)
                except TypeError:
                    storage_media.put_new(media_record_id, blob, ts_utc=ts_utc)
    else:
        # Blob exists; do not rewrite.
        pass

    deduped = existed

    record_id = f"{run_id}/evidence.input.file/{input_id}"
    payload: dict[str, Any] = {
        "record_type": "evidence.input.file",
        "schema_version": 1,
        "run_id": str(run_id),
        "ts_utc": str(ts_utc),
        "input_id": str(input_id),
        "source_path": str(file_path),
        "sha256": str(sha256_hex),
        "size_bytes": int(size_bytes),
        "media_record_id": str(media_record_id),
        "deduped": bool(deduped),
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})

    # Always write/replace this metadata record (idempotent for same input_id).
    if hasattr(storage_meta, "put_replace"):
        storage_meta.put_replace(record_id, payload, ts_utc=ts_utc)
    else:
        storage_meta.put(record_id, payload, ts_utc=ts_utc)

    if event_builder is not None:
        try:
            event_builder.journal_event("ingest.file", payload, ts_utc=ts_utc)
        except Exception:
            pass
        try:
            event_builder.ledger_entry(
                "ingest.file",
                inputs=[],
                outputs=[{"record_id": record_id, "record_type": "evidence.input.file"}],
                payload={"event": "ingest.file", "record_id": record_id, "media_record_id": media_record_id, "deduped": deduped},
                ts_utc=ts_utc,
            )
        except Exception:
            pass

    return IngestResult(
        input_id=input_id,
        media_record_id=media_record_id,
        sha256=sha256_hex,
        size_bytes=size_bytes,
        deduped=deduped,
    )

