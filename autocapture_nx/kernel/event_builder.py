"""Event builder helpers for journal and ledger entries."""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.errors import ConfigError
from autocapture_nx.kernel.evidence import validate_evidence_record
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.ids import prefixed_id
from autocapture_nx.kernel.policy_snapshot import policy_snapshot_hash, policy_snapshot_payload
from autocapture_nx.kernel.timebase import normalize_time, utc_iso_z, tz_offset_minutes


class EventBuilder:
    def __init__(self, config: dict[str, Any], journal, ledger, anchor=None) -> None:
        self._config = config
        self._journal = journal
        self._ledger = ledger
        self._anchor = anchor
        self._run_id = str(config.get("runtime", {}).get("run_id", ""))
        self._policy_hash: str | None = None
        self._ledger_seq = 0
        self._lock = threading.Lock()
        self._tzid = str(config.get("runtime", {}).get("timezone") or "UTC")
        anchor_cfg = config.get("storage", {}).get("anchor", {}) if isinstance(config, dict) else {}
        self._anchor_every_entries = int(anchor_cfg.get("every_entries", 0)) if anchor is not None else 0
        self._anchor_every_minutes = float(anchor_cfg.get("every_minutes", 0)) if anchor is not None else 0.0
        self._anchor_entry_count = 0
        self._last_anchor_ts: datetime | None = None
        self._last_anchor: dict[str, Any] | None = None

    @property
    def run_id(self) -> str:
        return self._run_id

    def ledger_head(self) -> str | None:
        if hasattr(self._ledger, "head_hash"):
            return self._ledger.head_hash()
        return None

    def last_anchor(self) -> dict[str, Any] | None:
        return dict(self._last_anchor) if self._last_anchor else None

    def policy_snapshot_hash(self) -> str:
        if self._policy_hash is None:
            payload = policy_snapshot_payload(self._config)
            self._policy_hash = policy_snapshot_hash(payload)
        return self._policy_hash

    def journal_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        ts_utc: str | None = None,
        tzid: str | None = None,
        offset_minutes: int | None = None,
    ) -> str:
        tzid = str(tzid or self._tzid or "UTC")
        if not ts_utc:
            normalized = normalize_time(tzid=tzid)
            ts_utc = normalized.ts_utc
            if offset_minutes is None:
                offset_minutes = normalized.offset_minutes
        if offset_minutes is None:
            # Preserve caller-supplied ts_utc while ensuring offset is set.
            try:
                dt = datetime.fromisoformat(str(ts_utc).replace("Z", "+00:00"))
            except Exception:
                dt = datetime.now(timezone.utc)
            offset_minutes = tz_offset_minutes(tzid, at_utc=dt.astimezone(timezone.utc))
        if isinstance(payload, dict):
            payload = dict(payload)
            if "run_id" not in payload and self._run_id:
                payload["run_id"] = self._run_id
            if "record_type" in payload and "run_id" in payload:
                validate_evidence_record(payload, event_id)
        return self._journal.append_event(
            event_type,
            payload,
            event_id=event_id,
            ts_utc=ts_utc,
            tzid=tzid,
            offset_minutes=int(offset_minutes),
        )

    def capture_stage(
        self,
        record_id: str,
        record_type: str,
        *,
        ts_utc: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_payload = {"record_id": record_id, "record_type": record_type, "stage": "staged"}
        if payload:
            event_payload.update(payload)
        return self.journal_event("capture.stage", event_payload, ts_utc=ts_utc)

    def capture_commit(
        self,
        record_id: str,
        record_type: str,
        *,
        ts_utc: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_payload = {"record_id": record_id, "record_type": record_type, "stage": "committed"}
        if payload:
            event_payload.update(payload)
        return self.journal_event("capture.commit", event_payload, ts_utc=ts_utc)

    def capture_unavailable(
        self,
        record_id: str,
        record_type: str,
        reason: str,
        *,
        ts_utc: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_payload = {"record_id": record_id, "record_type": record_type, "reason": reason}
        if payload:
            event_payload.update(payload)
        return self.journal_event("capture.unavailable", event_payload, ts_utc=ts_utc)

    def ledger_entry(
        self,
        stage: str,
        inputs: list[str],
        outputs: list[str],
        *,
        payload: dict[str, Any] | None = None,
        entry_id: str | None = None,
        ts_utc: str | None = None,
    ) -> str:
        with self._lock:
            seq = self._ledger_seq
            self._ledger_seq += 1
        if isinstance(payload, dict) and "record_type" in payload and "run_id" in payload:
            validate_evidence_record(payload, entry_id)
        if not ts_utc:
            ts_utc = utc_iso_z(datetime.now(timezone.utc))
        else:
            # Normalize to a stable Z suffix.
            try:
                ts_utc = utc_iso_z(datetime.fromisoformat(str(ts_utc).replace("Z", "+00:00")))
            except Exception:
                ts_utc = str(ts_utc)
        if not entry_id:
            entry_id = prefixed_id(self._run_id, f"ledger.{stage}", seq)
        entry = {
            "record_type": "ledger.entry",
            "schema_version": 1,
            "entry_id": entry_id,
            "ts_utc": ts_utc,
            "tzid": self._tzid,
            "offset_minutes": tz_offset_minutes(self._tzid),
            "stage": stage,
            "inputs": inputs,
            "outputs": outputs,
            "policy_snapshot_hash": self.policy_snapshot_hash(),
        }
        if payload is not None:
            entry["payload"] = payload
        ledger_hash = self._ledger.append(entry)
        if self._anchor:
            self._anchor_entry_count += 1
            now = datetime.fromisoformat(ts_utc)
            should_anchor = False
            if self._last_anchor is None:
                should_anchor = True
            if self._anchor_every_entries and self._anchor_entry_count >= self._anchor_every_entries:
                should_anchor = True
            if self._anchor_every_minutes:
                if self._last_anchor_ts is None:
                    should_anchor = True
                else:
                    elapsed = (now - self._last_anchor_ts).total_seconds()
                    if elapsed >= (self._anchor_every_minutes * 60.0):
                        should_anchor = True
            if should_anchor:
                self._last_anchor = self._anchor.anchor(ledger_hash)
                self._last_anchor_ts = now
                self._anchor_entry_count = 0
        return ledger_hash

    def failure_event(
        self,
        event_type: str,
        *,
        stage: str,
        error: Exception,
        inputs: list[str],
        outputs: list[str],
        payload: dict[str, Any] | None = None,
        ts_utc: str | None = None,
        retryable: bool | None = None,
    ) -> str:
        if not ts_utc:
            ts_utc = utc_iso_z(datetime.now(timezone.utc))
        failure_payload = {
            "event": event_type,
            "stage": stage,
            "error": str(error),
            "error_class": error.__class__.__name__,
            "retryable": bool(retryable) if retryable is not None else False,
        }
        if payload:
            failure_payload.update(payload)
        event_id = self.journal_event(event_type, failure_payload, ts_utc=ts_utc)
        self.ledger_entry(
            event_type,
            inputs=inputs,
            outputs=outputs,
            payload=failure_payload,
            ts_utc=ts_utc,
        )
        return event_id


def _canonicalize_config_for_hash(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _canonicalize_config_for_hash(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonicalize_config_for_hash(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ConfigError("Config contains NaN/Inf, which is not supported.")
        if obj.is_integer():
            return int(obj)
        return {"__float__": format(obj, ".15g")}
    return obj
