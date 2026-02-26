from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tools.verify_metadata_projection_alignment import evaluate_alignment


def _init_with_projection(path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            """
            CREATE TABLE metadata (
                id TEXT PRIMARY KEY,
                record_type TEXT,
                ts_utc TEXT,
                payload TEXT,
                run_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE metadata_projection (
                id TEXT PRIMARY KEY,
                record_type TEXT,
                ts_utc TEXT,
                ts_epoch REAL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _put_metadata(path: Path, record_id: str, payload: dict[str, object]) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
            (
                record_id,
                str(payload.get("record_type") or ""),
                str(payload.get("ts_utc") or ""),
                json.dumps(payload, sort_keys=True),
                str(payload.get("run_id") or ""),
            ),
        )
        con.commit()
    finally:
        con.close()


def _put_projection(path: Path, record_id: str, record_type: str, ts_utc: str) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "INSERT INTO metadata_projection (id, record_type, ts_utc, ts_epoch) VALUES (?, ?, ?, NULL)",
            (record_id, record_type, ts_utc),
        )
        con.commit()
    finally:
        con.close()


def test_evaluate_alignment_ok_when_counts_match() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "metadata.db"
        _init_with_projection(db)
        payload = {
            "schema_version": 1,
            "record_type": "evidence.capture.frame",
            "run_id": "run_1",
            "ts_utc": "2026-02-26T00:00:00Z",
        }
        _put_metadata(db, "run_1/evidence.capture.frame/1", payload)
        _put_projection(db, "run_1/evidence.capture.frame/1", "evidence.capture.frame", "2026-02-26T00:00:00Z")

        out = evaluate_alignment(db_path=db, record_types=["evidence.capture.frame"])
        assert bool(out.get("ok", False)) is True
        assert int(out.get("mismatch_count", 0) or 0) == 0
        rows = out.get("rows", [])
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["match"] is True


def test_evaluate_alignment_detects_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "metadata.db"
        _init_with_projection(db)
        payload = {
            "schema_version": 1,
            "record_type": "derived.sst.state",
            "run_id": "run_1",
            "ts_utc": "2026-02-26T00:00:00Z",
        }
        _put_metadata(db, "run_1/derived.sst.state/1", payload)
        out = evaluate_alignment(db_path=db, record_types=["derived.sst.state"])
        assert bool(out.get("ok", True)) is False
        assert int(out.get("mismatch_count", 0) or 0) == 1
        rows = out.get("rows", [])
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["match"] is False
        assert int(rows[0]["delta"]) == 1


def test_evaluate_alignment_fails_without_projection_table() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "metadata.db"
        con = sqlite3.connect(str(db))
        try:
            con.execute(
                """
                CREATE TABLE metadata (
                    id TEXT PRIMARY KEY,
                    record_type TEXT,
                    ts_utc TEXT,
                    payload TEXT,
                    run_id TEXT
                )
                """
            )
            con.commit()
        finally:
            con.close()

        out = evaluate_alignment(db_path=db, record_types=["evidence.capture.frame"])
        assert bool(out.get("ok", True)) is False
        assert str(out.get("error") or "") == "metadata_projection_table_missing"


def test_evaluate_alignment_handles_malformed_db() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "metadata.db"
        db.write_bytes(b"not-a-sqlite-db")
        out = evaluate_alignment(db_path=db, record_types=["evidence.capture.frame"])
        assert bool(out.get("ok", True)) is False
        assert str(out.get("error") or "").startswith("database_error:")
