from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autocapture_nx.ingest.handoff_ingest import HandoffIngestor, auto_drain_handoff_spool


def _write_handoff_metadata(path: Path, rows: list[tuple[str, dict]]) -> None:
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


def _count_dest_records(db_path: Path, record_type: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM metadata WHERE record_type = ?", (record_type,))
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


class HandoffIngestTests(unittest.TestCase):
    def test_handoff_ingest_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            handoff = root / "handoff-1"
            dest = root / "dest"
            (handoff / "media").mkdir(parents=True, exist_ok=True)
            (handoff / "media" / "rid_frame_1.blob").write_bytes(b"frame-bytes")
            payload = {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-20T00:00:00Z",
                "blob_path": "media/rid_frame_1.blob",
                "content_hash": "frame_hash_1",
                "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/1", "content_hash": "uia_hash_1"},
                "input_ref": {"record_id": "run_test/evidence.input.batch/1"},
            }
            _write_handoff_metadata(
                handoff / "metadata.db",
                [("run_test/evidence.capture.frame/1", payload)],
            )
            ingestor = HandoffIngestor(dest, mode="copy", strict=True)

            first = ingestor.ingest_handoff_dir(handoff)
            self.assertEqual(first.metadata_rows_copied, 1)
            self.assertEqual(first.media_files_copied, 1)
            self.assertEqual(first.stage1_complete_records, 1)
            self.assertEqual(first.stage1_retention_marked_records, 1)
            self.assertEqual(first.stage1_missing_retention_marker_count, 0)
            marker = json.loads((handoff / "reap_eligible.json").read_text(encoding="utf-8"))
            self.assertEqual(marker.get("schema"), "autocapture.handoff.reap_eligible.v1")
            self.assertEqual(int(marker.get("counts", {}).get("stage1_complete_records", 0)), 1)
            self.assertEqual(int(marker.get("counts", {}).get("stage1_retention_marked_records", 0)), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "evidence.capture.frame"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "derived.ingest.stage1.complete"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "retention.eligible"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "system.ingest.handoff.completed"), 1)

            second = ingestor.ingest_handoff_dir(handoff)
            self.assertEqual(second.metadata_rows_copied, 0)
            self.assertEqual(second.media_files_copied, 0)
            self.assertEqual(second.stage1_complete_records, 1)
            self.assertEqual(second.stage1_retention_marked_records, 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "evidence.capture.frame"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "derived.ingest.stage1.complete"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "retention.eligible"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "system.ingest.handoff.completed"), 1)

    def test_handoff_ingest_missing_media_fails_no_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            handoff = root / "handoff-2"
            dest = root / "dest"
            handoff.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-20T00:00:00Z",
                "blob_path": "media/missing.blob",
            }
            _write_handoff_metadata(
                handoff / "metadata.db",
                [("run_test/evidence.capture.frame/1", payload)],
            )
            ingestor = HandoffIngestor(dest, mode="copy", strict=True)
            with self.assertRaises(FileNotFoundError):
                ingestor.ingest_handoff_dir(handoff)
            self.assertFalse((handoff / "reap_eligible.json").exists())
            if (dest / "metadata.db").exists():
                self.assertEqual(_count_dest_records(dest / "metadata.db", "evidence.capture.frame"), 0)

    def test_handoff_ingest_hardlink_mode_fallbacks_to_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            handoff = root / "handoff-3"
            dest = root / "dest"
            (handoff / "media").mkdir(parents=True, exist_ok=True)
            (handoff / "media" / "rid_frame_1.blob").write_bytes(b"frame-bytes")
            payload = {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-20T00:00:00Z",
                "blob_path": "media/rid_frame_1.blob",
                "content_hash": "frame_hash_1",
                "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/1", "content_hash": "uia_hash_1"},
                "input_ref": {"record_id": "run_test/evidence.input.batch/1"},
            }
            _write_handoff_metadata(
                handoff / "metadata.db",
                [("run_test/evidence.capture.frame/1", payload)],
            )
            ingestor = HandoffIngestor(dest, mode="hardlink", strict=True)
            with patch("autocapture_nx.ingest.handoff_ingest.os.link", side_effect=OSError("xdev")):
                result = ingestor.ingest_handoff_dir(handoff)
            self.assertEqual(result.media_files_linked, 0)
            self.assertEqual(result.media_files_copied, 1)
            self.assertEqual(result.stage1_complete_records, 1)
            self.assertEqual(result.stage1_retention_marked_records, 1)
            self.assertTrue((dest / "media" / "rid_frame_1.blob").exists())

    def test_auto_drain_handoff_spool_marks_stage1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            spool = root / "spool"
            handoff = spool / "handoff-1"
            dest = root / "dest"
            (handoff / "media").mkdir(parents=True, exist_ok=True)
            (handoff / "media" / "rid_frame_1.blob").write_bytes(b"frame-bytes")
            payload = {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-20T00:00:00Z",
                "blob_path": "media/rid_frame_1.blob",
                "content_hash": "frame_hash_1",
                "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/1", "content_hash": "uia_hash_1"},
                "input_ref": {"record_id": "run_test/evidence.input.batch/1"},
            }
            _write_handoff_metadata(handoff / "metadata.db", [("run_test/evidence.capture.frame/1", payload)])
            cfg = {
                "storage": {"data_dir": str(dest), "spool_dir": str(spool)},
                "processing": {"idle": {"handoff_ingest": {"enabled": True, "mode": "copy", "strict": True}}},
            }

            first = auto_drain_handoff_spool(cfg)
            self.assertTrue(bool(first.get("ok", False)))
            self.assertEqual(int(first.get("processed", 0)), 1)
            self.assertEqual(int(first.get("stage1_complete_records", 0)), 1)
            self.assertEqual(int(first.get("stage1_retention_marked_records", 0)), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "derived.ingest.stage1.complete"), 1)
            self.assertEqual(_count_dest_records(dest / "metadata.db", "retention.eligible"), 1)

            second = auto_drain_handoff_spool(cfg)
            self.assertTrue(bool(second.get("ok", False)))
            self.assertEqual(int(second.get("processed", 0)), 0)
            self.assertGreaterEqual(int(second.get("skipped_marked", 0)), 1)


if __name__ == "__main__":
    unittest.main()
