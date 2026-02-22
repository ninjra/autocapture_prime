from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.query import _read_ledger_head_fast


def _write_ledger(path: Path, hashes: list[str]) -> None:
    rows = []
    for idx, entry_hash in enumerate(hashes):
        rows.append(
            {
                "record_type": "ledger.entry",
                "schema_version": 1,
                "entry_id": f"run/ledger/{idx}",
                "ts_utc": f"2026-02-22T00:00:{idx:02d}Z",
                "stage": "query.execute",
                "inputs": [],
                "outputs": [],
                "policy_snapshot_hash": "policy",
                "payload": {"event": "query.execute"},
                "prev_hash": hashes[idx - 1] if idx > 0 else None,
                "entry_hash": entry_hash,
            }
        )
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_read_ledger_head_fast_returns_last_entry_hash(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.ndjson"
    _write_ledger(ledger, ["hash_a", "hash_b", "hash_c"])
    assert _read_ledger_head_fast(str(ledger)) == "hash_c"


def test_read_ledger_head_fast_handles_small_tail_window(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.ndjson"
    hashes = [f"hash_{idx:05d}" for idx in range(200)]
    _write_ledger(ledger, hashes)
    assert _read_ledger_head_fast(str(ledger), max_tail_bytes=1024) == hashes[-1]


def test_read_ledger_head_fast_missing_file_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ndjson"
    assert _read_ledger_head_fast(str(missing)) is None
