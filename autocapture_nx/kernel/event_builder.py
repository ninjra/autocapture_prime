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

    @property
    def run_id(self) -> str:
        return self._run_id

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
            self._anchor.anchor(ledger_hash)
        return ledger_hash
