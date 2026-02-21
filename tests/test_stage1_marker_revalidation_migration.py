from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.stage1 import stage1_complete_record_id


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT)"
        )
        con.commit()
    finally:
        con.close()


def _insert_record(path: Path, record_id: str, payload: dict[str, object]) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "INSERT INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
            (
                record_id,
                json.dumps(payload, sort_keys=True),
                str(payload.get("record_type") or ""),
                str(payload.get("ts_utc") or ""),
                str(payload.get("run_id") or ""),
            ),
        )
        con.commit()
    finally:
        con.close()


def _get_record(path: Path, record_id: str) -> dict[str, object]:
    con = sqlite3.connect(str(path))
    try:
        row = con.execute("SELECT payload FROM metadata WHERE id = ?", (record_id,)).fetchone()
        assert row is not None
        return json.loads(str(row[0]))
    finally:
        con.close()


class Stage1MarkerRevalidationMigrationTests(unittest.TestCase):
    def test_upgrades_legacy_marker_when_stage1_complete_exists(self) -> None:
        mod = _load_module("tools/migrations/revalidate_stage1_markers.py", "stage1_marker_revalidate_1")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            _init_db(db_path)
            frame_id = "run1/evidence.capture.frame/11"
            _insert_record(
                db_path,
                stage1_complete_record_id(frame_id),
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "source_record_id": frame_id,
                    "complete": True,
                },
            )
            marker_id = "run1/retention.eligible/legacy11"
            _insert_record(
                db_path,
                marker_id,
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "eligible": True,
                },
            )

            summary = mod.revalidate_stage1_markers(db_path, dry_run=False)

            self.assertEqual(int(summary.get("updated") or 0), 1)
            marker = _get_record(db_path, marker_id)
            self.assertTrue(bool(marker.get("stage1_contract_validated", False)))
            self.assertFalse(bool(marker.get("quarantine_pending", False)))

    def test_quarantines_marker_when_stage1_complete_missing(self) -> None:
        mod = _load_module("tools/migrations/revalidate_stage1_markers.py", "stage1_marker_revalidate_2")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            _init_db(db_path)
            frame_id = "run1/evidence.capture.frame/12"
            marker_id = "run1/retention.eligible/legacy12"
            _insert_record(
                db_path,
                marker_id,
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "eligible": True,
                    "stage1_contract_validated": True,
                    "quarantine_pending": False,
                },
            )

            summary = mod.revalidate_stage1_markers(db_path, dry_run=False)

            self.assertEqual(int(summary.get("updated") or 0), 1)
            marker = _get_record(db_path, marker_id)
            self.assertFalse(bool(marker.get("stage1_contract_validated", False)))
            self.assertTrue(bool(marker.get("quarantine_pending", False)))

    def test_dry_run_reports_without_writing(self) -> None:
        mod = _load_module("tools/migrations/revalidate_stage1_markers.py", "stage1_marker_revalidate_3")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            _init_db(db_path)
            frame_id = "run1/evidence.capture.frame/13"
            marker_id = "run1/retention.eligible/legacy13"
            _insert_record(
                db_path,
                marker_id,
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "eligible": True,
                },
            )

            summary = mod.revalidate_stage1_markers(db_path, dry_run=True)

            self.assertEqual(int(summary.get("updated") or 0), 1)
            marker = _get_record(db_path, marker_id)
            self.assertFalse(bool(marker.get("stage1_contract_validated", False)))
            self.assertFalse(bool(marker.get("quarantine_pending", False)))

    def test_seeds_from_source_db_into_derived_db(self) -> None:
        mod = _load_module("tools/migrations/revalidate_stage1_markers.py", "stage1_marker_revalidate_4")
        with tempfile.TemporaryDirectory() as tmp:
            source_db = Path(tmp) / "metadata.db"
            derived_db = Path(tmp) / "derived" / "stage1_derived.db"
            derived_db.parent.mkdir(parents=True, exist_ok=True)
            _init_db(source_db)
            _init_db(derived_db)
            frame_id = "run1/evidence.capture.frame/21"
            stage1_id = stage1_complete_record_id(frame_id)
            marker_id = "run1/retention.eligible/legacy21"
            _insert_record(
                source_db,
                stage1_id,
                {
                    "record_type": "derived.ingest.stage1.complete",
                    "run_id": "run1",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "complete": True,
                },
            )
            _insert_record(
                source_db,
                marker_id,
                {
                    "record_type": "retention.eligible",
                    "run_id": "run1",
                    "source_record_id": frame_id,
                    "source_record_type": "evidence.capture.frame",
                    "eligible": True,
                },
            )

            summary = mod.revalidate_stage1_markers(derived_db, source_db_path=source_db, dry_run=False)

            self.assertEqual(int(summary.get("seeded_stage1") or 0), 1)
            self.assertEqual(int(summary.get("seeded_retention") or 0), 1)
            marker = _get_record(derived_db, marker_id)
            self.assertTrue(bool(marker.get("stage1_contract_validated", False)))
            self.assertFalse(bool(marker.get("quarantine_pending", False)))


if __name__ == "__main__":
    unittest.main()
