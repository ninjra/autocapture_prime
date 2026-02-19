"""Evidence retention (media-only) with batch logging."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.metadata_store import is_evidence_record


@dataclass(frozen=True)
class RetentionResult:
    ts_utc: str
    cutoff_ts_utc: str
    attempted: int
    deleted: int
    skipped: int
    missing: int
    batch_id: str | None
    dry_run: bool


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _extract_ts(record: dict[str, Any]) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in ("ts_utc", "ts_start_utc", "ts_end_utc"):
        value = record.get(key)
        if value:
            return str(value)
    return None


def _parse_retention_spec(spec: Any) -> int | None:
    if spec is None:
        return None
    text = str(spec).strip().lower()
    if not text or text in {"infinite", "inf", "off", "none", "disabled", "0"}:
        return None
    match = re.match(r"^(\d+)\s*(d|day|days|h|hr|hour|hours|m|min|minute|minutes|s|sec|second|seconds)?$", text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2) or "d"
    if unit.startswith("h"):
        return value * 3600
    if unit.startswith("m"):
        return value * 60
    if unit.startswith("s"):
        return value
    return value * 86400


def _candidate_ids(metadata: Any, cutoff_ts: str, limit: int) -> Iterable[str]:
    if hasattr(metadata, "query_time_window"):
        try:
            return metadata.query_time_window(None, cutoff_ts, limit=limit)
        except Exception:
            pass
    cutoff_epoch = None
    try:
        cutoff_epoch = _parse_iso(cutoff_ts).timestamp()
    except Exception:
        cutoff_epoch = None
    ids: list[tuple[float, str]] = []
    for record_id in getattr(metadata, "keys", lambda: [])():
        record = metadata.get(record_id, {})
        ts_val = _extract_ts(record)
        if not ts_val:
            continue
        try:
            ts_key = _parse_iso(ts_val).timestamp()
        except Exception:
            continue
        if cutoff_epoch is not None and ts_key > cutoff_epoch:
            continue
        ids.append((ts_key, record_id))
    ids.sort(key=lambda item: (item[0], item[1]))
    return [record_id for _ts, record_id in ids[: max(0, int(limit))]]


def _eligible_evidence(record_id: str, record: dict[str, Any]) -> bool:
    return _eligible_evidence_record(record_id, record)


def retention_eligibility_record_id(record_id: str) -> str:
    run_id = str(record_id).split("/", 1)[0] if "/" in str(record_id) else "run"
    component = encode_record_id_component(str(record_id))
    return f"{run_id}/retention.eligible/{component}"


def mark_evidence_retention_eligible(
    metadata: Any,
    record_id: str,
    record: dict[str, Any],
    *,
    reason: str = "processed",
    ts_utc: str | None = None,
    event_builder: Any | None = None,
    logger: Any | None = None,
) -> str | None:
    if metadata is None:
        return None
    rid = retention_eligibility_record_id(record_id)
    existing = metadata.get(rid, None) if hasattr(metadata, "get") else None
    if isinstance(existing, dict):
        return rid
    run_id = str(record.get("run_id") or (record_id.split("/", 1)[0] if "/" in record_id else "run"))
    ts_val = str(ts_utc or datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "retention.eligible",
        "run_id": run_id,
        "ts_utc": ts_val,
        "source_record_id": str(record_id),
        "source_record_type": str(record.get("record_type") or ""),
        "reason": str(reason or "processed"),
        "eligible": True,
    }
    try:
        if hasattr(metadata, "put_new"):
            metadata.put_new(rid, payload)
        else:
            metadata.put(rid, payload)
    except Exception:
        return None
    if event_builder is not None:
        try:
            event_builder.journal_event("storage.retention.eligible", payload, event_id=rid, ts_utc=ts_val)
            event_builder.ledger_entry(
                "storage.retention.eligible",
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
            logger.log("storage.retention.eligible", {"source_record_id": str(record_id), "reason": str(reason or "processed")})
        except Exception:
            pass
    return rid


def _retention_ready(metadata: Any, record_id: str) -> bool:
    marker_id = retention_eligibility_record_id(record_id)
    marker = metadata.get(marker_id, None) if hasattr(metadata, "get") else None
    if not isinstance(marker, dict):
        return False
    if str(marker.get("record_type") or "") != "retention.eligible":
        return False
    return bool(marker.get("eligible", True))


def _eligible_evidence_record(
    record_id: str,
    record: dict[str, Any],
    *,
    metadata: Any | None = None,
    processed_only: bool = False,
    images_only: bool = False,
) -> bool:
    if not isinstance(record, dict):
        return False
    if not is_evidence_record(record):
        return False
    record_type = str(record.get("record_type", ""))
    if images_only:
        content_type = str(record.get("content_type") or "")
        is_image = content_type.startswith("image/") or record_type.startswith("evidence.capture.frame")
        if not is_image:
            return False
    if processed_only:
        if metadata is None:
            return False
        if not _retention_ready(metadata, record_id):
            return False
    if record_type.startswith("evidence.capture.") or record_type.startswith("evidence.audio."):
        return True
    if "content_hash" in record or "content_size" in record:
        return True
    return False


def apply_evidence_retention(
    metadata: Any,
    media: Any,
    config: dict[str, Any],
    *,
    dry_run: bool = False,
    event_builder: Any | None = None,
    logger: Any | None = None,
) -> RetentionResult | None:
    storage_cfg = config.get("storage", {})
    if bool(storage_cfg.get("no_deletion_mode", True)):
        return None
    retention_cfg = storage_cfg.get("retention", {}) if isinstance(storage_cfg, dict) else {}
    spec = retention_cfg.get("evidence", "infinite")
    seconds = _parse_retention_spec(spec)
    if seconds is None or seconds <= 0:
        return None
    processed_only = bool(retention_cfg.get("processed_only", False))
    images_only = bool(retention_cfg.get("images_only", retention_cfg.get("image_only", False)))
    max_delete = int(retention_cfg.get("max_delete_per_run", 500))
    max_delete = max(0, max_delete)
    if max_delete == 0:
        return None
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=seconds)
    cutoff_ts = cutoff.isoformat()
    ts_utc = now.isoformat()
    attempted = 0
    deleted = 0
    skipped = 0
    missing = 0
    deleted_ids: list[str] = []
    for record_id in _candidate_ids(metadata, cutoff_ts, max_delete):
        record = metadata.get(record_id, {})
        if not _eligible_evidence_record(
            record_id,
            record,
            metadata=metadata,
            processed_only=processed_only,
            images_only=images_only,
        ):
            skipped += 1
            continue
        attempted += 1
        if dry_run:
            deleted_ids.append(record_id)
            deleted += 1
            continue
        try:
            removed = bool(media.delete(record_id))
        except Exception:
            removed = False
        if removed:
            deleted += 1
            deleted_ids.append(record_id)
        else:
            missing += 1

    batch_id = None
    if deleted_ids and bool(retention_cfg.get("record_batches", True)):
        run_id = ensure_run_id(config)
        batch_id = prefixed_id(run_id, "derived.retention.batch", int(time.time() * 1000))
        batch_payload = {
            "record_type": "derived.retention.batch",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "cutoff_ts_utc": cutoff_ts,
            "deleted_ids": list(deleted_ids),
        }
        encoded = json.dumps(batch_payload, sort_keys=True).encode("utf-8")
        try:
            if hasattr(media, "put_new"):
                media.put_new(batch_id, encoded, ts_utc=ts_utc)
            else:
                media.put(batch_id, encoded, ts_utc=ts_utc)
            import hashlib

            content_hash = hashlib.sha256(encoded).hexdigest()
        except Exception:
            content_hash = None
        meta_payload = {
            "record_type": "derived.retention.batch",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "cutoff_ts_utc": cutoff_ts,
            "deleted_count": int(deleted),
            "content_size": int(len(encoded)),
        }
        if content_hash:
            meta_payload["content_hash"] = content_hash
        try:
            if hasattr(metadata, "put_new"):
                metadata.put_new(batch_id, meta_payload)
            else:
                metadata.put(batch_id, meta_payload)
        except Exception:
            pass

    result = RetentionResult(
        ts_utc=ts_utc,
        cutoff_ts_utc=cutoff_ts,
        attempted=int(attempted),
        deleted=int(deleted),
        skipped=int(skipped),
        missing=int(missing),
        batch_id=batch_id,
        dry_run=bool(dry_run),
    )

    payload = json.loads(json.dumps(result.__dict__))
    payload["event"] = "storage.retention"
    if event_builder is not None:
        try:
            event_builder.journal_event("storage.retention", payload, ts_utc=ts_utc)
            event_builder.ledger_entry(
                "storage.retention",
                inputs=[],
                outputs=[batch_id] if batch_id else [],
                payload=payload,
                ts_utc=ts_utc,
            )
        except Exception:
            pass
    if logger is not None and deleted:
        try:
            logger.log(
                "storage.retention",
                {
                    "deleted": int(deleted),
                    "attempted": int(attempted),
                    "missing": int(missing),
                    "cutoff_ts_utc": cutoff_ts,
                },
            )
        except Exception:
            pass
    return result


class StorageRetentionMonitor:
    def __init__(self, system: Any) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._builder = None
        self._logger = None
        self._metadata = None
        self._media = None
        if hasattr(system, "get"):
            try:
                self._builder = system.get("event.builder")
            except Exception:
                self._builder = None
            try:
                self._logger = system.get("observability.logger")
            except Exception:
                self._logger = None
            try:
                self._metadata = system.get("storage.metadata")
            except Exception:
                self._metadata = None
            try:
                self._media = system.get("storage.media")
            except Exception:
                self._media = None
        self._last_run = 0.0

    def _interval_s(self) -> float:
        storage_cfg = self._config.get("storage", {}) if isinstance(self._config, dict) else {}
        retention_cfg = storage_cfg.get("retention", {}) if isinstance(storage_cfg, dict) else {}
        return float(retention_cfg.get("interval_s", 3600))

    def due(self) -> bool:
        storage_cfg = self._config.get("storage", {}) if isinstance(self._config, dict) else {}
        if bool(storage_cfg.get("no_deletion_mode", True)):
            return False
        retention_cfg = storage_cfg.get("retention", {}) if isinstance(storage_cfg, dict) else {}
        spec = retention_cfg.get("evidence", "infinite")
        if _parse_retention_spec(spec) is None:
            return False
        interval = max(60.0, self._interval_s())
        return (time.time() - self._last_run) >= interval

    def record(self) -> RetentionResult | None:
        if self._metadata is None or self._media is None:
            return None
        result = apply_evidence_retention(
            self._metadata,
            self._media,
            self._config,
            event_builder=self._builder,
            logger=self._logger,
        )
        if result is None:
            return None
        self._last_run = time.time()
        return result
