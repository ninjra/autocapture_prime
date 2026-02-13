"""Staged multi-store evidence writes with rollback markers (EXEC-06).

This module implements a conservative, raw-first, append-only transaction model:

1. write blob (raw artifact)
2. write metadata (evidence record)
3. append journal event (tx begin marker)
4. append ledger entry (commit marker)

If an exception occurs mid-flight, we do NOT delete local data. Instead we
record rollback markers in journal + ledger when possible.

Recovery scans for journal begin markers that lack the corresponding ledger
commit marker and deterministically completes the missing steps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.kernel.hashing import sha256_bytes


@dataclass(frozen=True)
class EvidenceWriteReport:
    ok: bool
    evidence_id: str
    stages_completed: list[str]
    tx_id: str | None = None
    error: str | None = None
    rollback_recorded: bool = False


def _tx_id_for(*, evidence_id: str, record: dict[str, Any], blob_sha256: str) -> str:
    payload = {
        "evidence_id": str(evidence_id),
        "blob_sha256": str(blob_sha256),
        "record": record,
    }
    return sha256_bytes(canonical_dumps(payload).encode("utf-8"))


def write_evidence_staged(
    *,
    evidence_id: str,
    blob: bytes,
    record: dict[str, Any],
    media: Any,
    metadata: Any,
    events: Any | None,
    # Test-only fault injection hook; should be None in production.
    fault_after_stage: str | None = None,
) -> EvidenceWriteReport:
    stages: list[str] = []
    rollback_recorded = False

    def _rollback(reason: str, stage: str) -> None:
        nonlocal rollback_recorded
        if events is None:
            return
        payload = {
            "schema_version": 1,
            "event": "evidence.write.rollback",
            "evidence_id": str(evidence_id),
            "stage": str(stage),
            "reason": str(reason),
            "stages_completed": list(stages),
        }
        try:
            if hasattr(events, "journal_event"):
                # Keep event_id stable for dedupe; evidence ids are already run-scoped.
                events.journal_event("evidence.write.rollback", payload, event_id=str(evidence_id))
        except Exception:
            pass
        try:
            if hasattr(events, "ledger_entry"):
                events.ledger_entry(
                    "evidence.write.rollback",
                    inputs=[],
                    outputs=[str(evidence_id)],
                    payload=payload,
                    entry_id=str(evidence_id),
                )
        except Exception:
            pass
        rollback_recorded = True

    blob_sha = sha256_bytes(bytes(blob))
    tx_id = _tx_id_for(evidence_id=evidence_id, record=record, blob_sha256=blob_sha)

    try:
        # Stage 1: write blob (raw-first).
        if hasattr(media, "put_new"):
            media.put_new(evidence_id, blob)
        else:
            media.put(evidence_id, blob)
        stages.append("blob")
        if fault_after_stage == "blob":
            raise RuntimeError("fault_injected_after_blob")

        # Stage 2: write metadata record.
        if hasattr(metadata, "put_new"):
            metadata.put_new(evidence_id, record)
        else:
            metadata.put(evidence_id, record)
        stages.append("metadata")
        if fault_after_stage == "metadata":
            raise RuntimeError("fault_injected_after_metadata")

        # Stage 3: append journal.
        if events is not None and hasattr(events, "journal_event"):
            events.journal_event(
                "evidence.write.begin",
                {
                    "schema_version": 1,
                    "event": "evidence.write.begin",
                    "tx_id": tx_id,
                    "evidence_id": str(evidence_id),
                    "blob_sha256": blob_sha,
                    # Store enough to deterministically recover metadata if needed.
                    "record": record,
                    "stages_completed": list(stages),
                },
                event_id=str(tx_id),
            )
        stages.append("journal")
        if fault_after_stage == "journal":
            raise RuntimeError("fault_injected_after_journal")

        # Stage 4: append ledger.
        if events is not None and hasattr(events, "ledger_entry"):
            events.ledger_entry(
                "evidence.write.commit",
                inputs=[],
                outputs=[str(evidence_id)],
                payload={
                    "schema_version": 1,
                    "event": "evidence.write.commit",
                    "tx_id": tx_id,
                    "evidence_id": str(evidence_id),
                    "blob_sha256": blob_sha,
                },
                entry_id=str(tx_id),
            )
        stages.append("ledger")
        return EvidenceWriteReport(
            ok=True,
            evidence_id=evidence_id,
            stages_completed=stages,
            tx_id=tx_id,
            rollback_recorded=rollback_recorded,
        )
    except Exception as exc:
        _rollback(str(exc), stages[-1] if stages else "start")
        return EvidenceWriteReport(
            ok=False,
            evidence_id=evidence_id,
            stages_completed=stages,
            tx_id=tx_id,
            error=f"{type(exc).__name__}: {exc}",
            rollback_recorded=rollback_recorded,
        )


def recover_incomplete_evidence_writes(
    *,
    data_dir: str | Path,
    metadata: Any,
    media: Any,
    events: Any | None,
) -> dict[str, Any]:
    """Best-effort deterministic recovery for staged evidence writes.

    We scan the journal for `evidence.write.begin` markers. If we do not find a
    corresponding ledger commit marker (tx_id present as `entry_id`) we:
    - ensure blob exists (raw-first: never delete)
    - ensure metadata exists (re-write from journal snapshot if missing)
    - append the missing ledger commit marker
    """

    root = Path(str(data_dir))
    journal_path = root / "journal.ndjson"
    ledger_path = root / "ledger.ndjson"
    if not journal_path.exists():
        return {"ok": True, "recovered": 0, "skipped": 0, "reason": "journal_missing"}

    begin: dict[str, dict[str, Any]] = {}
    for line in journal_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        if str(row.get("event_type") or "") != "evidence.write.begin":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        tx_id = str(payload.get("tx_id") or "")
        if not tx_id:
            continue
        begin[tx_id] = payload

    committed: set[str] = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            entry_id = str(row.get("entry_id") or "")
            if entry_id:
                committed.add(entry_id)

    recovered = 0
    skipped = 0
    for tx_id, payload in sorted(begin.items()):
        if tx_id in committed:
            skipped += 1
            continue
        evidence_id = str(payload.get("evidence_id") or "")
        record = payload.get("record") if isinstance(payload.get("record"), dict) else None
        blob_sha = str(payload.get("blob_sha256") or "")
        if not evidence_id or record is None:
            skipped += 1
            continue

        # Ensure blob exists (best-effort). If missing, we record a rollback marker.
        blob_ok = True
        try:
            if hasattr(media, "has"):
                blob_ok = bool(media.has(evidence_id))
            elif hasattr(media, "get"):
                _ = media.get(evidence_id)
        except Exception:
            blob_ok = False
        if not blob_ok:
            if events is not None and hasattr(events, "failure_event"):
                try:
                    events.failure_event(
                        "evidence.write.recovery_failed",
                        stage="recover.blob_missing",
                        error=RuntimeError("blob_missing"),
                        inputs=[],
                        outputs=[evidence_id],
                        payload={"tx_id": tx_id, "blob_sha256": blob_sha},
                        retryable=False,
                    )
                except Exception:
                    pass
            skipped += 1
            continue

        # Ensure metadata exists.
        meta_ok = True
        try:
            if hasattr(metadata, "has"):
                meta_ok = bool(metadata.has(evidence_id))
            elif hasattr(metadata, "get"):
                _ = metadata.get(evidence_id)
        except Exception:
            meta_ok = False
        if not meta_ok:
            try:
                if hasattr(metadata, "put_new"):
                    metadata.put_new(evidence_id, record)
                else:
                    metadata.put(evidence_id, record)
            except Exception:
                # Cannot recover without metadata.
                skipped += 1
                continue

        # Append missing ledger commit marker.
        if events is not None and hasattr(events, "ledger_entry"):
            try:
                events.ledger_entry(
                    "evidence.write.commit",
                    inputs=[],
                    outputs=[evidence_id],
                    payload={
                        "schema_version": 1,
                        "event": "evidence.write.commit",
                        "tx_id": tx_id,
                        "evidence_id": evidence_id,
                        "blob_sha256": blob_sha,
                        "recovered": True,
                    },
                    entry_id=str(tx_id),
                )
                recovered += 1
            except Exception:
                skipped += 1
                continue
        else:
            skipped += 1
            continue

        if events is not None and hasattr(events, "journal_event"):
            try:
                events.journal_event(
                    "evidence.write.recovered",
                    {
                        "schema_version": 1,
                        "event": "evidence.write.recovered",
                        "tx_id": tx_id,
                        "evidence_id": evidence_id,
                    },
                    event_id=str(tx_id),
                )
            except Exception:
                pass

    return {"ok": True, "recovered": recovered, "skipped": skipped, "candidates": len(begin)}
