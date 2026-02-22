from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, record_type TEXT, ts_utc TEXT, payload TEXT, run_id TEXT)"
    )
    conn.commit()
    return conn


def _put(conn: sqlite3.Connection, record_id: str, payload: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
        (
            str(record_id),
            str(payload.get("record_type") or ""),
            str(payload.get("ts_utc") or ""),
            json.dumps(payload, sort_keys=True),
            str(payload.get("run_id") or ""),
        ),
    )
    conn.commit()


class ReportStageLineageQueryabilityToolTests(unittest.TestCase):
    def test_main_writes_json_and_markdown_reports(self) -> None:
        mod = _load_module("tools/report_stage_lineage_queryability.py", "report_stage_lineage_queryability_tool_1")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            out_json = Path(td) / "lineage.json"
            out_md = Path(td) / "lineage.md"
            conn = _open_db(db)
            _put(
                conn,
                "run1/evidence.capture.frame/1",
                {
                    "record_type": "evidence.capture.frame",
                    "run_id": "run1",
                    "ts_utc": "2026-02-21T10:00:00Z",
                    "blob_path": "media/frame1.png",
                    "content_hash": "frame_hash_1",
                },
            )
            conn.close()

            argv_prev = list(sys.argv)
            try:
                sys.argv = [
                    "report_stage_lineage_queryability.py",
                    "--db",
                    str(db),
                    "--frame-limit",
                    "10",
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                ]
                rc = mod.main()
            finally:
                sys.argv = argv_prev
            self.assertEqual(rc, 0)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_md.exists())
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))
            self.assertEqual(int(payload.get("frame_lineage_total") or 0), 1)
            rows = payload.get("frame_lineage", []) if isinstance(payload.get("frame_lineage", []), list) else []
            self.assertEqual(len(rows), 1)
            self.assertIn("plugins", rows[0])


if __name__ == "__main__":
    unittest.main()
