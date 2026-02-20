"""Shared helpers to persist deterministic obs.uia.* records from UIA snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _frame_dims(record: dict[str, Any]) -> tuple[int, int]:
    width = _safe_int(record.get("width") or record.get("frame_width") or 0)
    height = _safe_int(record.get("height") or record.get("frame_height") or 0)
    return max(1, width), max(1, height)


def _source_ts(record: dict[str, Any]) -> str:
    for key in ("ts_utc", "ts_start_utc", "ts_end_utc"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return _utc_now()


def _uia_doc_id(uia_record_id: str, section: str, index: int) -> str:
    from plugins.builtin.processing_sst_uia_context.plugin import _uia_doc_id as plugin_uia_doc_id

    return plugin_uia_doc_id(uia_record_id, section, index)


def _uia_extract_snapshot_dict(value: Any) -> dict[str, Any] | None:
    from plugins.builtin.processing_sst_uia_context.plugin import _extract_snapshot_dict

    return _extract_snapshot_dict(value)


def _frame_uia_expected_ids(uia_record_id: str) -> dict[str, str]:
    return {
        "obs.uia.focus": _uia_doc_id(str(uia_record_id), "focus", 0),
        "obs.uia.context": _uia_doc_id(str(uia_record_id), "context", 0),
        "obs.uia.operable": _uia_doc_id(str(uia_record_id), "operable", 0),
    }


def _ensure_frame_uia_docs(
    metadata: Any,
    *,
    source_record_id: str,
    record: dict[str, Any],
    dataroot: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"required": False, "ok": True, "inserted": 0, "reason": "invalid_record"}
    if str(record.get("record_type") or "") != "evidence.capture.frame":
        return {"required": False, "ok": True, "inserted": 0, "reason": "not_frame"}
    uia_ref = record.get("uia_ref") if isinstance(record.get("uia_ref"), dict) else {}
    uia_record_id = str(uia_ref.get("record_id") or "").strip()
    if not uia_record_id:
        return {"required": False, "ok": True, "inserted": 0, "reason": "missing_uia_ref"}
    expected_ids = _frame_uia_expected_ids(uia_record_id)
    existing_by_kind: dict[str, bool] = {}
    for kind, doc_id in expected_ids.items():
        row = metadata.get(doc_id, None) if hasattr(metadata, "get") else None
        existing_by_kind[kind] = isinstance(row, dict) and str(row.get("record_type") or "") == kind
    if all(existing_by_kind.values()):
        return {"required": True, "ok": True, "inserted": 0, "reason": "already_present"}

    snapshot_value = metadata.get(uia_record_id, None) if hasattr(metadata, "get") else None
    snapshot = _uia_extract_snapshot_dict(snapshot_value)
    if not isinstance(snapshot, dict):
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_missing"}
    if str(snapshot.get("record_type") or "").strip() not in {"", "evidence.uia.snapshot"}:
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_record_type_invalid"}

    try:
        from plugins.builtin.processing_sst_uia_context.plugin import _parse_settings as _uia_parse_settings
        from plugins.builtin.processing_sst_uia_context.plugin import _snapshot_to_docs as _uia_snapshot_to_docs
    except Exception:
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_plugin_unavailable"}

    width, height = _frame_dims(record)
    docs = _uia_snapshot_to_docs(
        plugin_id="builtin.processing.sst.uia_context",
        frame_width=int(width),
        frame_height=int(height),
        uia_ref=uia_ref,
        snapshot=snapshot,
        cfg=_uia_parse_settings({"dataroot": str(dataroot)}),
    )
    if not docs:
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_to_docs_empty"}

    run_id = str(record.get("run_id") or (source_record_id.split("/", 1)[0] if "/" in source_record_id else "run"))
    ts_utc = _source_ts(record)
    inserted = 0
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("doc_id") or "").strip()
        record_type = str(doc.get("record_type") or "").strip()
        if not doc_id or record_type not in {"obs.uia.focus", "obs.uia.context", "obs.uia.operable"}:
            continue
        payload: dict[str, Any] = {
            "schema_version": 1,
            "record_type": record_type,
            "run_id": run_id,
            "ts_utc": ts_utc,
            "source_record_id": str(source_record_id),
            "source_record_type": str(record.get("record_type") or ""),
            "doc_kind": str(doc.get("doc_kind") or record_type),
            "text": str(doc.get("text") or ""),
            "provider_id": str(doc.get("provider_id") or "builtin.processing.sst.uia_context"),
            "stage": str(doc.get("stage") or "index.text"),
            "confidence_bp": _safe_int(doc.get("confidence_bp") or 8500),
            "bboxes": doc.get("bboxes") if isinstance(doc.get("bboxes"), list) else [],
            "uia_record_id": str(doc.get("uia_record_id") or uia_record_id),
            "uia_content_hash": str(doc.get("uia_content_hash") or uia_ref.get("content_hash") or snapshot.get("content_hash") or ""),
            "hwnd": str(doc.get("hwnd") or snapshot.get("hwnd") or ""),
            "window_title": str(doc.get("window_title") or (snapshot.get("window", {}) if isinstance(snapshot.get("window"), dict) else {}).get("title") or ""),
            "window_pid": _safe_int(doc.get("window_pid") or (snapshot.get("window", {}) if isinstance(snapshot.get("window"), dict) else {}).get("pid") or 0),
            "meta": doc.get("meta") if isinstance(doc.get("meta"), dict) else {},
        }
        try:
            if hasattr(metadata, "put_new"):
                metadata.put_new(doc_id, payload)
            else:
                metadata.put(doc_id, payload)
            inserted += 1
        except FileExistsError:
            continue
        except Exception:
            return {"required": True, "ok": False, "inserted": int(inserted), "reason": "doc_insert_failed"}

    for kind, doc_id in expected_ids.items():
        row = metadata.get(doc_id, None) if hasattr(metadata, "get") else None
        if not (isinstance(row, dict) and str(row.get("record_type") or "") == kind):
            return {"required": True, "ok": False, "inserted": int(inserted), "reason": "doc_missing_after_insert"}
    return {"required": True, "ok": True, "inserted": int(inserted), "reason": "ok"}
