"""Event builder helpers for journal and ledger entries."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.ids import prefixed_id


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
            self._policy_hash = sha256_text(dumps(self._config))
        return self._policy_hash

    def journal_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        ts_utc: str | None = None,
        tzid: str | None = None,
        offset_minutes: int = 0,
    ) -> str:
        return self._journal.append_event(
            event_type,
            payload,
            event_id=event_id,
            ts_utc=ts_utc,
            tzid=tzid,
            offset_minutes=offset_minutes,
        )

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
        if not ts_utc:
            ts_utc = datetime.now(timezone.utc).isoformat()
        if not entry_id:
            entry_id = prefixed_id(self._run_id, f"ledger.{stage}", seq)
        entry = {
            "record_type": "ledger.entry",
            "schema_version": 1,
            "entry_id": entry_id,
            "ts_utc": ts_utc,
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
            ts_utc = datetime.now(timezone.utc).isoformat()
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
