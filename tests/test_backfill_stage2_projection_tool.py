from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tools.migrations.backfill_stage2_projection_docs import backfill_stage2_projection_docs


def _write_metadata(path: Path, rows: list[tuple[str, dict]]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
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
        for record_id, payload in rows:
            conn.execute(
                "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
                (
                    record_id,
                    str(payload.get("record_type") or ""),
                    str(payload.get("ts_utc") or ""),
                    json.dumps(payload, sort_keys=True),
                    str(payload.get("run_id") or ""),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _count_rows(path: Path, record_type: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM metadata WHERE record_type = ?", (record_type,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def test_backfill_stage2_projection_docs_writes_derived_extra_docs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "metadata.db"
        frame_id = "run_test/evidence.capture.frame/1"
        uia_id = "run_test/evidence.uia.snapshot/1"
        frame = {
            "schema_version": 1,
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "uia_ref": {"record_id": uia_id, "content_hash": "uia_hash_1"},
            "width": 1920,
            "height": 1080,
        }
        snapshot = {
            "schema_version": 1,
            "record_type": "evidence.uia.snapshot",
            "record_id": uia_id,
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "window": {"title": "Remote Desktop Web Client", "process_path": "C:\\Program Files\\Chrome\\chrome.exe", "pid": 4242},
            "focus_path": [{"name": "NCAAW game starts 8:00 PM", "role": "Text", "rect": [10, 10, 300, 40]}],
            "context_peers": [],
            "operables": [],
            "content_hash": "uia_hash_1",
        }
        _write_metadata(db_path, [(frame_id, frame), (uia_id, snapshot)])

        first = backfill_stage2_projection_docs(db_path, dry_run=False, limit=None, snapshot_read=True)
        assert int(first.get("inserted_docs", 0) or 0) >= 1
        assert int(first.get("inserted_states", 0) or 0) == 1
        assert int(first.get("stage2_marker_inserted", 0) or 0) == 1
        assert int(first.get("stage2_marker_complete", 0) or 0) == 1
        assert int(first.get("error_frames", 0) or 0) == 0
        assert _count_rows(db_path, "derived.sst.text.extra") >= 1
        assert _count_rows(db_path, "derived.sst.state") == 1
        assert _count_rows(db_path, "derived.ingest.stage2.complete") == 1

        second = backfill_stage2_projection_docs(db_path, dry_run=False, limit=None, snapshot_read=True)
        assert int(second.get("inserted_docs", 0) or 0) == 0
        assert int(second.get("inserted_states", 0) or 0) == 0
