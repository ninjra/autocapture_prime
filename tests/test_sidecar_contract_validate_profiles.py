from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _write_metadata_db(root: Path) -> None:
    db = root / "metadata.db"
    con = sqlite3.connect(str(db))
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
              id TEXT PRIMARY KEY,
              payload TEXT NOT NULL,
              record_type TEXT,
              ts_utc TEXT,
              run_id TEXT
            )
            """
        )
        rows = [
            {
                "id": "run1/evidence.capture.frame/1",
                "record_type": "evidence.capture.frame",
                "ts_utc": "2026-02-16T00:00:00Z",
                "run_id": "run1",
            },
            {
                "id": "run1/derived.input.summary/1",
                "record_type": "derived.input.summary",
                "ts_utc": "2026-02-16T00:00:01Z",
                "run_id": "run1",
            },
        ]
        for row in rows:
            payload = json.dumps(
                {
                    "schema_version": 1,
                    "record_type": row["record_type"],
                    "ts_utc": row["ts_utc"],
                    "run_id": row["run_id"],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            cur.execute(
                "INSERT INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
                (row["id"], payload, row["record_type"], row["ts_utc"], row["run_id"]),
            )
        con.commit()
    finally:
        con.close()


def _write_minimum_mode_b_data(root: Path) -> None:
    (root / "media").mkdir(parents=True, exist_ok=True)
    (root / "media" / "sample.blob").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "activity").mkdir(parents=True, exist_ok=True)
    (root / "activity" / "activity_signal.json").write_text(
        json.dumps(
            {
                "ts_utc": "2026-02-16T00:00:02Z",
                "idle_seconds": 0,
                "user_active": True,
                "source": "tests",
                "seq": 1,
            }
        ),
        encoding="utf-8",
    )
    _write_metadata_db(root)


def _run_validator(dataroot: Path, profile: str) -> tuple[int, dict[str, object]]:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "sidecar_contract_validate.py"),
            "--dataroot",
            str(dataroot),
            "--max-journal-lines",
            "10",
            "--contract-profile",
            profile,
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout)
    return int(proc.returncode), payload


def test_strict_profile_requires_journal_and_ledger(tmp_path: Path) -> None:
    _write_minimum_mode_b_data(tmp_path)
    rc, payload = _run_validator(tmp_path, "strict")
    assert rc == 2
    assert payload["ok"] is False
    assert payload["profiles"]["metadata_first"] is True
    assert payload["profiles"]["strict"] is False


def test_metadata_first_profile_allows_missing_journal_and_ledger(tmp_path: Path) -> None:
    _write_minimum_mode_b_data(tmp_path)
    rc, payload = _run_validator(tmp_path, "metadata_first")
    assert rc == 0
    assert payload["ok"] is True
    assert payload["profiles"]["metadata_first"] is True
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert "journal_missing_or_invalid" in warnings
    assert "ledger_missing" in warnings


def test_strict_profile_passes_when_journal_and_ledger_present(tmp_path: Path) -> None:
    _write_minimum_mode_b_data(tmp_path)
    (tmp_path / "journal.ndjson").write_text('{"event_type":"capture.frame","payload":{"record_type":"evidence.capture.frame"}}\n', encoding="utf-8")
    (tmp_path / "ledger.ndjson").write_text('{"record_type":"ledger.entry"}\n', encoding="utf-8")
    rc, payload = _run_validator(tmp_path, "strict")
    assert rc == 0
    assert payload["ok"] is True
    assert payload["profiles"]["strict"] is True
