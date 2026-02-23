from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tools.migrations.backfill_state_tape import backfill_state_tape


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


def _state_payload(record_id: str, frame_id: str, ts_ms: int) -> dict:
    return {
        "schema_version": 1,
        "record_type": "derived.sst.state",
        "run_id": "run_test",
        "record_id": record_id,
        "artifact_id": record_id,
        "ts_utc": "2026-02-20T00:00:00Z",
        "screen_state": {
            "state_id": f"state_{frame_id}",
            "frame_id": frame_id,
            "frame_index": 0,
            "ts_ms": ts_ms,
            "phash": "a" * 64,
            "image_sha256": "b" * 64,
            "width": 1280,
            "height": 720,
            "tokens": [{"token_id": "tok_0", "text": "hello", "norm_text": "hello", "bbox": [0, 0, 100, 20]}],
            "visible_apps": ["chrome.exe"],
            "element_graph": {"elements": [], "edges": []},
            "text_blocks": [],
            "tables": [],
            "spreadsheets": [],
            "code_blocks": [],
            "charts": [],
        },
    }


def test_backfill_state_tape_writes_spans() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_path = root / "metadata.db"
        state_db = root / "state" / "state_tape.db"
        rows = [
            ("run_test/derived.sst.state/rid1", _state_payload("run_test/derived.sst.state/rid1", "frame1", 1000)),
            ("run_test/derived.sst.state/rid2", _state_payload("run_test/derived.sst.state/rid2", "frame2", 2000)),
        ]
        _write_metadata(db_path, rows)

        summary = backfill_state_tape(db_path, state_db_path=state_db, max_loops=20, max_states_per_run=100)
        assert bool(summary.get("ok", False))
        assert bool(summary.get("done", False))
        assert int((summary.get("delta") or {}).get("state_span", 0) or 0) >= 1
