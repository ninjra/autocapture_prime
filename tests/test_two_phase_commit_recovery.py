from __future__ import annotations

import json
from pathlib import Path


class _MemStore:
    def __init__(self) -> None:
        self._d: dict[str, object] = {}

    def put_new(self, key: str, value: object) -> None:
        if key in self._d:
            raise KeyError("exists")
        self._d[key] = value

    def put(self, key: str, value: object) -> None:
        self._d[key] = value

    def get(self, key: str) -> object:
        return self._d[key]

    def has(self, key: str) -> bool:
        return key in self._d


def _ctx_config(tmp_path: Path) -> dict:
    return {
        "storage": {"data_dir": str(tmp_path)},
        "runtime": {"run_id": "run_test", "timezone": "UTC"},
    }


def test_exec06_recovery_completes_missing_ledger_marker(tmp_path: Path) -> None:
    from autocapture_nx.kernel.evidence_writer import recover_incomplete_evidence_writes, _tx_id_for
    from autocapture_nx.kernel.event_builder import EventBuilder
    from autocapture_nx.plugin_system.api import PluginContext
    from plugins.builtin.journal_basic.plugin import JournalWriter
    from plugins.builtin.ledger_basic.plugin import LedgerWriter
    from autocapture_nx.kernel.hashing import sha256_bytes

    config = _ctx_config(tmp_path)
    ctx = PluginContext(
        config=config,
        get_capability=lambda _name: None,
        logger=lambda _m: None,
        rng=None,
        rng_seed=None,
        rng_seed_hex=None,
    )
    journal = JournalWriter("builtin.journal.basic", ctx)
    ledger = LedgerWriter("builtin.ledger.basic", ctx)
    events = EventBuilder(config, journal, ledger, anchor=None)

    media = _MemStore()
    metadata = _MemStore()

    evidence_id = "run_test/evidence.screenshot/1"
    blob = b"blob-bytes"
    record = {
        "record_type": "evidence.screenshot",
        "schema_version": 1,
        "evidence_id": evidence_id,
        "ts_utc": "2026-01-01T00:00:00Z",
        "media_id": evidence_id,
        "mime_type": "image/png",
        "sha256": sha256_bytes(blob),
        "width": 1,
        "height": 1,
    }
    blob_sha = sha256_bytes(blob)
    tx_id = _tx_id_for(evidence_id=evidence_id, record=record, blob_sha256=blob_sha)

    # Simulate a crash after journal begin but before ledger commit.
    media.put_new(evidence_id, blob)
    metadata.put_new(evidence_id, record)
    events.journal_event(
        "evidence.write.begin",
        {
            "schema_version": 1,
            "event": "evidence.write.begin",
            "tx_id": tx_id,
            "evidence_id": evidence_id,
            "blob_sha256": blob_sha,
            "record": record,
            "stages_completed": ["blob", "metadata"],
        },
        event_id=tx_id,
    )

    ledger_path = tmp_path / "ledger.ndjson"
    assert not ledger_path.exists() or tx_id not in ledger_path.read_text(encoding="utf-8", errors="ignore")

    report = recover_incomplete_evidence_writes(data_dir=tmp_path, metadata=metadata, media=media, events=events)
    assert report["ok"] is True
    assert report["recovered"] == 1

    ledger_text = ledger_path.read_text(encoding="utf-8")
    assert tx_id in ledger_text

    # Idempotent: running again should not append another commit for same tx_id.
    before_lines = ledger_text.strip().splitlines()
    report2 = recover_incomplete_evidence_writes(data_dir=tmp_path, metadata=metadata, media=media, events=events)
    assert report2["ok"] is True
    after_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(after_lines) == len(before_lines)

    # Ensure the ledger entry is valid JSON per line.
    _ = [json.loads(line) for line in after_lines]

