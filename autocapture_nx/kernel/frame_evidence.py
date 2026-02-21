"""Helpers for creating explicit frame evidence records from segments."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import encode_record_id_component


def _guess_content_type(blob: bytes) -> str:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "application/octet-stream"


def _frame_record_id(run_id: str, segment_id: str, frame_index: int) -> str:
    component = encode_record_id_component(segment_id)
    return f"{run_id}/frame/segment/{component}/{int(frame_index)}"


def ensure_frame_evidence(
    *,
    config: dict[str, Any],
    metadata: Any,
    media: Any,
    record_id: str,
    record: dict[str, Any],
    frame_bytes: bytes,
    event_builder: Any | None = None,
    logger: Any | None = None,
) -> tuple[str, dict[str, Any]]:
    """Create a deterministic evidence.capture.frame record for segment-derived frames.

    Returns (frame_record_id, frame_record). If creation fails or is disabled, returns the input record.
    """
    record_type = str(record.get("record_type", ""))
    if record_type == "evidence.capture.frame":
        return record_id, record
    if record_type != "evidence.capture.segment":
        return record_id, record

    state_cfg = config.get("processing", {}).get("state_layer", {}) if isinstance(config, dict) else {}
    if not bool(state_cfg.get("enabled", False)) or not bool(state_cfg.get("emit_frame_evidence", False)):
        return record_id, record
    if metadata is None or media is None:
        return record_id, record

    run_id = str(record.get("run_id") or (record_id.split("/", 1)[0] if "/" in record_id else "run"))
    frame_index = int(state_cfg.get("segment_frame_index", 0) or 0)
    frame_record_id = _frame_record_id(run_id, record_id, frame_index)
    existing = metadata.get(frame_record_id, None) if hasattr(metadata, "get") else None
    if isinstance(existing, dict):
        return frame_record_id, existing

    ts_utc = record.get("ts_start_utc") or record.get("ts_utc") or datetime.now(timezone.utc).isoformat()
    width = int(record.get("width", 0) or 0)
    height = int(record.get("height", 0) or 0)
    content_hash = hashlib.sha256(frame_bytes).hexdigest()
    payload: dict[str, Any] = {
        "record_type": "evidence.capture.frame",
        "run_id": run_id,
        "ts_utc": ts_utc,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "content_type": _guess_content_type(frame_bytes),
        "content_size": int(len(frame_bytes)),
        "content_hash": content_hash,
        "image_sha256": content_hash,
        "frame_index": frame_index,
        "parent_evidence_id": record_id,
        "segment_id": record.get("segment_id") or record_id,
        "source_segment_id": record_id,
        "policy_snapshot_hash": record.get("policy_snapshot_hash"),
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})

    try:
        if hasattr(media, "put_new"):
            try:
                media.put_new(frame_record_id, frame_bytes, ts_utc=ts_utc)
            except Exception:
                media.put(frame_record_id, frame_bytes, ts_utc=ts_utc)
        else:
            media.put(frame_record_id, frame_bytes, ts_utc=ts_utc)
    except Exception as exc:
        if logger is not None and hasattr(logger, "log"):
            logger.log("state.frame_evidence_media_error", {"record_id": frame_record_id, "error": str(exc)})
        return record_id, record

    try:
        if hasattr(metadata, "put_new"):
            try:
                metadata.put_new(frame_record_id, payload)
            except Exception:
                metadata.put(frame_record_id, payload)
        else:
            metadata.put(frame_record_id, payload)
    except Exception as exc:
        if logger is not None and hasattr(logger, "log"):
            logger.log("state.frame_evidence_meta_error", {"record_id": frame_record_id, "error": str(exc)})
        return record_id, record

    if event_builder is not None:
        try:
            event_builder.journal_event("capture.frame.derived", payload, event_id=frame_record_id, ts_utc=ts_utc)
            event_builder.ledger_entry(
                "capture.frame.derived",
                inputs=[record_id],
                outputs=[frame_record_id],
                payload=payload,
                entry_id=frame_record_id,
                ts_utc=ts_utc,
            )
        except Exception:
            pass

    return frame_record_id, payload
