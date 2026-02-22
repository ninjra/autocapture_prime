from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
    def test_resolve_db_path_falls_back_to_metadata_live(self) -> None:
        mod = _load_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool_0")
        with tempfile.TemporaryDirectory() as td:
            primary = Path(td) / "metadata.db"
            fallback = Path(td) / "metadata.live.db"
            # Deliberately create a non-sqlite primary and a valid fallback.
            primary.write_text("not a sqlite database", encoding="utf-8")
            conn = _open_db(fallback)
            conn.close()
            resolved, reason = mod._resolve_db_path(primary)
            self.assertEqual(resolved, fallback)
            self.assertEqual(reason, "fallback")

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
            self.assertEqual(int(out.get("frame_lineage_total") or 0), 1)
            rows = out.get("frame_lineage", []) if isinstance(out.get("frame_lineage", []), list) else []
            self.assertEqual(len(rows), 1)
            plugins = rows[0].get("plugins", {}) if isinstance(rows[0].get("plugins", {}), dict) else {}
            self.assertTrue(bool((plugins.get("stage1_complete") or {}).get("ok", False)))
            self.assertTrue(bool((plugins.get("retention_eligible") or {}).get("ok", False)))
            self.assertTrue(bool((plugins.get("obs_uia_focus") or {}).get("ok", False)))
            self.assertTrue(bool((plugins.get("obs_uia_context") or {}).get("ok", False)))
            self.assertTrue(bool((plugins.get("obs_uia_operable") or {}).get("ok", False)))

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

    def test_obs_source_linkage_mismatch_blocks_queryable(self) -> None:
        mod = _load_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool_3")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            derived = Path(td) / "derived" / "stage1_derived.db"
            derived.parent.mkdir(parents=True, exist_ok=True)
            conn = _open_db(db)
            dconn = _open_db(derived)
            frame_id = "run3/evidence.capture.frame/1"
            uia_record_id = "run3/evidence.uia.snapshot/1"
            frame = {
                "record_type": "evidence.capture.frame",
                "run_id": "run3",
                "ts_utc": "2026-02-21T03:00:00Z",
                "blob_path": "media/frame3.png",
                "content_hash": "frame_hash_3",
                "uia_ref": {"record_id": uia_record_id, "content_hash": "uia_hash_3", "ts_utc": "2026-02-21T03:00:00Z"},
                "input_ref": {"record_id": "run3/evidence.input.keyboard/1"},
            }
            _put(conn, frame_id, frame)
            _put(
                conn,
                uia_record_id,
                {
                    "record_type": "evidence.uia.snapshot",
                    "run_id": "run3",
                    "ts_utc": "2026-02-21T03:00:00Z",
                    "record_id": uia_record_id,
                },
            )
            _put(
                dconn,
                stage1_complete_record_id(frame_id),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run3",
                    "ts_utc": "2026-02-21T03:00:01Z",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "complete": True,
                    "uia_record_id": uia_record_id,
                    "uia_content_hash": "uia_hash_3",
                },
            )
            _put(
                dconn,
                retention_eligibility_record_id(frame_id),
                {
                    "record_type": "retention.eligible",
                    "run_id": "run3",
                    "ts_utc": "2026-02-21T03:00:02Z",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )
            wrong_source = "run3/evidence.capture.frame/WRONG"
            for kind, doc_id in _frame_uia_expected_ids(uia_record_id).items():
                _put(
                    dconn,
                    doc_id,
                    {
                        "record_type": kind,
                        "run_id": "run3",
                        "ts_utc": "2026-02-21T03:00:01Z",
                        "source_record_id": wrong_source,
                        "uia_record_id": uia_record_id,
                        "uia_content_hash": "uia_hash_3",
                        "hwnd": "0x777",
                        "window_title": "Bad Linkage",
                        "window_pid": 9090,
                        "bboxes": [[0, 0, 100, 100]],
                    },
                )
            conn.close()
            dconn.close()

            out = mod.run_audit(db, derived_db_path=derived, gap_seconds=60, sample_limit=3)
            summary = out.get("summary", {}) if isinstance(out.get("summary"), dict) else {}
            self.assertEqual(int(summary.get("frames_total") or 0), 1)
            self.assertEqual(int(summary.get("frames_blocked") or 0), 1)
            issues = out.get("issue_counts", {}) if isinstance(out.get("issue_counts"), dict) else {}
            self.assertGreater(int(issues.get("obs_uia_focus_missing_or_invalid", 0) or 0), 0)

    def test_frame_lineage_limit_is_enforced(self) -> None:
        mod = _load_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool_4")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            conn = _open_db(db)
            for idx in range(3):
                frame_id = f"run4/evidence.capture.frame/{idx+1}"
                _put(
                    conn,
                    frame_id,
                    {
                        "record_type": "evidence.capture.frame",
                        "run_id": "run4",
                        "ts_utc": f"2026-02-21T04:00:0{idx}Z",
                        "blob_path": f"media/frame{idx+1}.png",
                        "content_hash": f"frame_hash_{idx+1}",
                    },
                )
            conn.close()
            out = mod.run_audit(db, derived_db_path=None, gap_seconds=60, sample_limit=3, frame_report_limit=2)
            self.assertTrue(bool(out.get("ok", False)))
            self.assertEqual(int(out.get("frame_lineage_total") or 0), 3)
            self.assertEqual(int(out.get("frame_lineage_limit") or 0), 2)
            rows = out.get("frame_lineage", []) if isinstance(out.get("frame_lineage", []), list) else []
            self.assertEqual(len(rows), 2)

    def test_run_audit_retries_transient_sqlite_open_error(self) -> None:
        mod = _load_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool_5")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            conn = _open_db(db)
            _put(
                conn,
                "run5/evidence.capture.frame/1",
                {
                    "record_type": "evidence.capture.frame",
                    "run_id": "run5",
                    "ts_utc": "2026-02-21T05:00:00Z",
                    "blob_path": "media/frame1.png",
                    "content_hash": "frame_hash_1",
                },
            )
            conn.close()

            real_connect = sqlite3.connect
            calls = {"n": 0}

            def _connect(*args, **kwargs):  # type: ignore[no-untyped-def]
                calls["n"] += 1
                if calls["n"] == 1:
                    raise sqlite3.OperationalError("disk I/O error")
                return real_connect(*args, **kwargs)

            with mock.patch.object(mod.sqlite3, "connect", side_effect=_connect):
                out = mod.run_audit(db, derived_db_path=None, gap_seconds=60, sample_limit=3)
            self.assertTrue(bool(out.get("ok", False)))


if __name__ == "__main__":
    unittest.main()
