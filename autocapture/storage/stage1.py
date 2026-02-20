"""Stage 1 ingest completion + retention marker helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture.storage.retention import mark_evidence_retention_eligible
from autocapture.storage.retention import retention_eligibility_record_id


def stage1_complete_record_id(record_id: str) -> str:
    run_id = str(record_id).split("/", 1)[0] if "/" in str(record_id) else "run"
    component = encode_record_id_component(str(record_id))
    return f"{run_id}/derived.ingest.stage1.complete/{component}"


def is_stage1_complete_record(record_id: str, record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    record_type = str(record.get("record_type") or "")
    if record_type != "evidence.capture.frame":
        return False
    if not str(record.get("blob_path") or "").strip():
        return False
    if not str(record.get("content_hash") or "").strip():
        return False

    # Stage 1 must link frame->UIA snapshot by exact record_id.
    uia_ref = record.get("uia_ref") if isinstance(record.get("uia_ref"), dict) else None
    if not isinstance(uia_ref, dict):
        return False
    if not str(uia_ref.get("record_id") or "").strip():
        return False
    if not str(uia_ref.get("content_hash") or "").strip():
        return False

    # HID requirement: raw batch and/or linked summary reference.
    has_hid_link = False
    if isinstance(record.get("input_ref"), dict):
        has_hid_link = bool(str(record.get("input_ref", {}).get("record_id") or "").strip())
    if not has_hid_link and isinstance(record.get("input_batch_ref"), dict):
        has_hid_link = bool(str(record.get("input_batch_ref", {}).get("record_id") or "").strip())
    return has_hid_link


def mark_stage1_complete(
    metadata: Any,
    record_id: str,
    record: dict[str, Any],
    *,
    ts_utc: str | None = None,
    reason: str = "stage1_complete",
    event_builder: Any | None = None,
    logger: Any | None = None,
) -> tuple[str | None, bool]:
    if metadata is None:
        return None, False
    if not is_stage1_complete_record(record_id, record):
        return None, False

    rid = stage1_complete_record_id(record_id)
    existing = metadata.get(rid, None) if hasattr(metadata, "get") else None
    if isinstance(existing, dict):
        return rid, False

    run_id = str(record.get("run_id") or (record_id.split("/", 1)[0] if "/" in record_id else "run"))
    ts_val = str(ts_utc or datetime.now(timezone.utc).isoformat())
    uia_ref = record.get("uia_ref") if isinstance(record.get("uia_ref"), dict) else {}
    input_ref = record.get("input_ref") if isinstance(record.get("input_ref"), dict) else {}
    input_batch_ref = record.get("input_batch_ref") if isinstance(record.get("input_batch_ref"), dict) else {}
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "derived.ingest.stage1.complete",
        "run_id": run_id,
        "ts_utc": ts_val,
        "source_record_id": str(record_id),
        "source_record_type": str(record.get("record_type") or ""),
        "reason": str(reason or "stage1_complete"),
        "uia_record_id": str(uia_ref.get("record_id") or ""),
        "uia_content_hash": str(uia_ref.get("content_hash") or ""),
        "input_record_id": str(input_ref.get("record_id") or ""),
        "input_batch_record_id": str(input_batch_ref.get("record_id") or ""),
        "complete": True,
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    try:
        if hasattr(metadata, "put_new"):
            metadata.put_new(rid, payload)
        else:
            metadata.put(rid, payload)
    except Exception:
        return None, False

    if event_builder is not None:
        try:
            event_builder.journal_event("ingest.stage1.complete", payload, event_id=rid, ts_utc=ts_val)
            event_builder.ledger_entry(
                "ingest.stage1.complete",
                inputs=[str(record_id)],
                outputs=[rid],
                payload=payload,
                entry_id=rid,
                ts_utc=ts_val,
            )
        except Exception:
            pass
    if logger is not None:
        try:
            logger.log("ingest.stage1.complete", {"source_record_id": str(record_id)})
        except Exception:
            pass
    return rid, True


def mark_stage1_and_retention(
    metadata: Any,
    record_id: str,
    record: dict[str, Any],
    *,
    ts_utc: str | None = None,
    reason: str = "stage1_complete",
    event_builder: Any | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    stage1_id, stage1_inserted = mark_stage1_complete(
        metadata,
        record_id,
        record,
        ts_utc=ts_utc,
        reason=reason,
        event_builder=event_builder,
        logger=logger,
    )
    retention_reason = "stage1_complete" if stage1_id else str(reason or "idle_processed")
    retention_id = mark_evidence_retention_eligible(
        metadata,
        record_id,
        record,
        reason=retention_reason,
        ts_utc=ts_utc,
        event_builder=event_builder,
        logger=logger,
    )
    if retention_id is None:
        # Existing marker may already be present.
        fallback = retention_eligibility_record_id(record_id)
        existing = metadata.get(fallback, None) if hasattr(metadata, "get") else None
        if isinstance(existing, dict):
            retention_id = fallback
    return {
        "stage1_complete": bool(stage1_id),
        "stage1_inserted": bool(stage1_inserted),
        "stage1_record_id": stage1_id,
        "retention_record_id": retention_id,
        "retention_missing": retention_id is None,
    }
