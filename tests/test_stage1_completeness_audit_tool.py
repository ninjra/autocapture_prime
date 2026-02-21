from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import stage1_complete_record_id
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids


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


class Stage1CompletenessAuditToolTests(unittest.TestCase):
    def test_queryable_frame_emits_single_window(self) -> None:
        mod = _load_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool_1")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            derived = Path(td) / "derived" / "stage1_derived.db"
            derived.parent.mkdir(parents=True, exist_ok=True)
            conn = _open_db(db)
            dconn = _open_db(derived)
            frame_id = "run1/evidence.capture.frame/1"
            uia_record_id = "run1/evidence.uia.snapshot/1"
            frame = {
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": "2026-02-21T01:00:00Z",
                "blob_path": "media/frame1.png",
                "content_hash": "frame_hash_1",
                "uia_ref": {"record_id": uia_record_id, "content_hash": "uia_hash_1", "ts_utc": "2026-02-21T01:00:00Z"},
                "input_ref": {"record_id": "run1/evidence.input.keyboard/1"},
            }
            _put(conn, frame_id, frame)
            _put(
                conn,
                uia_record_id,
                {
                    "record_type": "evidence.uia.snapshot",
                    "run_id": "run1",
                    "ts_utc": "2026-02-21T01:00:00Z",
                    "record_id": uia_record_id,
                },
            )
            _put(
                dconn,
                stage1_complete_record_id(frame_id),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "ts_utc": "2026-02-21T01:00:01Z",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "complete": True,
                    "uia_record_id": uia_record_id,
                    "uia_content_hash": "uia_hash_1",
                },
            )
            _put(
                dconn,
                retention_eligibility_record_id(frame_id),
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "ts_utc": "2026-02-21T01:00:02Z",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )
            for kind, doc_id in _frame_uia_expected_ids(uia_record_id).items():
                _put(
                    dconn,
                    doc_id,
                    {
                        "record_type": kind,
                        "run_id": "run1",
                        "ts_utc": "2026-02-21T01:00:01Z",
                        "source_record_id": frame_id,
                        "uia_record_id": uia_record_id,
                        "uia_content_hash": "uia_hash_1",
                        "hwnd": "0x123",
                        "window_title": "Terminal",
                        "window_pid": 4242,
                        "bboxes": [[0, 0, 100, 100]],
                    },
                )
            conn.close()
            dconn.close()

            out = mod.run_audit(db, derived_db_path=derived, gap_seconds=60, sample_limit=3)
            self.assertTrue(bool(out.get("ok", False)))
            summary = out.get("summary", {}) if isinstance(out.get("summary"), dict) else {}
            self.assertEqual(int(summary.get("frames_total") or 0), 1)
            self.assertEqual(int(summary.get("frames_queryable") or 0), 1)
            self.assertEqual(int(summary.get("contiguous_queryable_windows") or 0), 1)
            self.assertEqual(len(out.get("queryable_windows") or []), 1)

    def test_missing_retention_marks_frame_blocked(self) -> None:
        mod = _load_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool_2")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            conn = _open_db(db)
            frame_id = "run2/evidence.capture.frame/1"
            _put(
                conn,
                frame_id,
                {
                    "record_type": "evidence.capture.frame",
                    "run_id": "run2",
                    "ts_utc": "2026-02-21T02:00:00Z",
                    "blob_path": "media/frame2.png",
                    "content_hash": "frame_hash_2",
                    "uia_ref": {"record_id": "run2/evidence.uia.snapshot/1", "content_hash": "uia_hash_2"},
                    "input_ref": {"record_id": "run2/evidence.input.keyboard/1"},
                },
            )
            conn.close()

            out = mod.run_audit(db, derived_db_path=None, gap_seconds=60, sample_limit=3)
            self.assertTrue(bool(out.get("ok", False)))
            summary = out.get("summary", {}) if isinstance(out.get("summary"), dict) else {}
            self.assertEqual(int(summary.get("frames_total") or 0), 1)
            self.assertEqual(int(summary.get("frames_blocked") or 0), 1)
            issues = out.get("issue_counts", {}) if isinstance(out.get("issue_counts"), dict) else {}
            self.assertGreater(int(issues.get("retention_eligible_missing_or_invalid", 0) or 0), 0)


if __name__ == "__main__":
    unittest.main()
