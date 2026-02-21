from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import stage1_complete_record_id
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_db(path: Path) -> None:
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
        conn.commit()
    finally:
        conn.close()


def _put(path: Path, record_id: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(str(path))
    try:
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


class ValidateStage1LineageToolTests(unittest.TestCase):
    def test_strict_passes_for_complete_chain(self) -> None:
        mod = _load_module("tools/validate_stage1_lineage.py", "validate_stage1_lineage_tool_1")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            _init_db(db)
            frame_id = "run1/evidence.capture.frame/1"
            uia_id = "run1/evidence.uia.snapshot/1"
            _put(
                db,
                frame_id,
                {
                    "record_type": "evidence.capture.frame",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "uia_ref": {"record_id": uia_id, "content_hash": "h1"},
                },
            )
            _put(
                db,
                uia_id,
                {
                    "record_type": "evidence.uia.snapshot",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "record_id": uia_id,
                    "content_hash": "h1",
                },
            )
            for kind, obs_id in _frame_uia_expected_ids(uia_id).items():
                _put(
                    db,
                    obs_id,
                    {
                        "record_type": kind,
                        "run_id": "run1",
                        "ts_utc": "2026-02-20T00:00:00Z",
                        "source_record_id": frame_id,
                        "uia_record_id": uia_id,
                        "uia_content_hash": "h1",
                        "hwnd": "100",
                        "window_title": "Editor",
                        "window_pid": 1234,
                        "bboxes": [[0.1, 0.2, 0.3, 0.4]],
                    },
                )
            _put(
                db,
                stage1_complete_record_id(frame_id),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "complete": True,
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "uia_record_id": uia_id,
                    "uia_content_hash": "h1",
                },
            )
            _put(
                db,
                retention_eligibility_record_id(frame_id),
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )

            out = mod.validate_stage1_lineage(db, strict=True, sample_count=3)
            self.assertTrue(bool(out.get("ok", False)))
            summary = out.get("summary", {}) if isinstance(out.get("summary", {}), dict) else {}
            self.assertEqual(int(summary.get("lineage_complete") or 0), 1)
            self.assertEqual(int(summary.get("lineage_incomplete") or 0), 0)

    def test_strict_fails_when_any_uia_lineage_incomplete(self) -> None:
        mod = _load_module("tools/validate_stage1_lineage.py", "validate_stage1_lineage_tool_2")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            _init_db(db)
            frame_ok = "run1/evidence.capture.frame/1"
            uia_ok = "run1/evidence.uia.snapshot/1"
            frame_bad = "run1/evidence.capture.frame/2"
            uia_bad = "run1/evidence.uia.snapshot/2"

            for frame_id, uia_id in ((frame_ok, uia_ok), (frame_bad, uia_bad)):
                _put(
                    db,
                    frame_id,
                    {
                        "record_type": "evidence.capture.frame",
                        "run_id": "run1",
                        "ts_utc": "2026-02-20T00:00:00Z",
                        "uia_ref": {"record_id": uia_id, "content_hash": "h"},
                    },
                )
                _put(
                    db,
                    uia_id,
                    {
                        "record_type": "evidence.uia.snapshot",
                        "run_id": "run1",
                        "ts_utc": "2026-02-20T00:00:00Z",
                        "record_id": uia_id,
                        "content_hash": "h",
                    },
                )

            # Complete one chain fully.
            for kind, obs_id in _frame_uia_expected_ids(uia_ok).items():
                _put(
                    db,
                    obs_id,
                    {
                        "record_type": kind,
                        "run_id": "run1",
                        "ts_utc": "2026-02-20T00:00:00Z",
                        "source_record_id": frame_ok,
                        "uia_record_id": uia_ok,
                        "uia_content_hash": "h",
                        "hwnd": "101",
                        "window_title": "Editor",
                        "window_pid": 1234,
                        "bboxes": [[0.1, 0.1, 0.2, 0.2]],
                    },
                )
            _put(
                db,
                stage1_complete_record_id(frame_ok),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "complete": True,
                    "source_record_id": frame_ok,
                    "source_record_type": "evidence.capture.frame",
                    "uia_record_id": uia_ok,
                    "uia_content_hash": "h",
                },
            )
            _put(
                db,
                retention_eligibility_record_id(frame_ok),
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "source_record_id": frame_ok,
                    "source_record_type": "evidence.capture.frame",
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )

            # Keep second chain incomplete (no obs/stage1/retention).
            out_relaxed = mod.validate_stage1_lineage(db, strict=False, sample_count=3)
            self.assertTrue(bool(out_relaxed.get("ok", False)))
            out_strict = mod.validate_stage1_lineage(db, strict=True, sample_count=3)
            self.assertFalse(bool(out_strict.get("ok", True)))
            reasons = [str(x) for x in (out_strict.get("fail_reasons") or [])]
            self.assertIn("strict_lineage_incomplete_nonzero", reasons)

    def test_strict_all_frames_fails_when_frame_missing_stage1_marker(self) -> None:
        mod = _load_module("tools/validate_stage1_lineage.py", "validate_stage1_lineage_tool_3")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            _init_db(db)
            frame_a = "run1/evidence.capture.frame/1"
            frame_b = "run1/evidence.capture.frame/2"
            for frame_id in (frame_a, frame_b):
                _put(
                    db,
                    frame_id,
                    {
                        "record_type": "evidence.capture.frame",
                        "run_id": "run1",
                        "ts_utc": "2026-02-20T00:00:00Z",
                        "uia_ref": {"record_id": f"run1/evidence.uia.snapshot/{frame_id[-1]}", "content_hash": "h"},
                    },
                )
            # Only frame A has stage1+retention.
            _put(
                db,
                stage1_complete_record_id(frame_a),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "complete": True,
                    "source_record_id": frame_a,
                    "source_record_type": "evidence.capture.frame",
                    "uia_record_id": "run1/evidence.uia.snapshot/1",
                    "uia_content_hash": "h",
                },
            )
            _put(
                db,
                retention_eligibility_record_id(frame_a),
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "source_record_id": frame_a,
                    "source_record_type": "evidence.capture.frame",
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )
            out = mod.validate_stage1_lineage(db, strict=False, strict_all_frames=True, sample_count=3)
            self.assertFalse(bool(out.get("ok", True)))
            reasons = [str(x) for x in (out.get("fail_reasons") or [])]
            self.assertIn("strict_all_frames_incomplete_nonzero", reasons)

    def test_strict_passes_with_stage1_records_in_derived_db(self) -> None:
        mod = _load_module("tools/validate_stage1_lineage.py", "validate_stage1_lineage_tool_4")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            derived = Path(td) / "derived" / "stage1_derived.db"
            derived.parent.mkdir(parents=True, exist_ok=True)
            _init_db(db)
            _init_db(derived)
            frame_id = "run1/evidence.capture.frame/1"
            uia_id = "run1/evidence.uia.snapshot/1"
            _put(
                db,
                frame_id,
                {
                    "record_type": "evidence.capture.frame",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "uia_ref": {"record_id": uia_id, "content_hash": "h1"},
                },
            )
            _put(
                db,
                uia_id,
                {
                    "record_type": "evidence.uia.snapshot",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "record_id": uia_id,
                    "content_hash": "h1",
                },
            )
            for kind, obs_id in _frame_uia_expected_ids(uia_id).items():
                _put(
                    derived,
                    obs_id,
                    {
                        "record_type": kind,
                        "run_id": "run1",
                        "ts_utc": "2026-02-20T00:00:00Z",
                        "source_record_id": frame_id,
                        "uia_record_id": uia_id,
                        "uia_content_hash": "h1",
                        "hwnd": "100",
                        "window_title": "Editor",
                        "window_pid": 1234,
                        "bboxes": [[0.1, 0.2, 0.3, 0.4]],
                    },
                )
            _put(
                derived,
                stage1_complete_record_id(frame_id),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "complete": True,
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "uia_record_id": uia_id,
                    "uia_content_hash": "h1",
                },
            )
            _put(
                derived,
                retention_eligibility_record_id(frame_id),
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )

            out = mod.validate_stage1_lineage(db, derived_db_path=derived, strict=True, sample_count=3, strict_all_frames=True)
            self.assertTrue(bool(out.get("ok", False)))
            summary = out.get("summary", {}) if isinstance(out.get("summary"), dict) else {}
            counts = summary.get("record_counts", {}) if isinstance(summary.get("record_counts"), dict) else {}
            self.assertEqual(int(counts.get("obs.uia.focus") or 0), 1)


if __name__ == "__main__":
    unittest.main()
