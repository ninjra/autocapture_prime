from __future__ import annotations

import unittest
from typing import Any

from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids
from autocapture.storage.retention import mark_evidence_retention_eligible
from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import mark_stage1_complete
from autocapture.storage.stage1 import (
    mark_stage1_and_retention,
    mark_stage1_plugin_completion,
    mark_stage2_complete,
    stage1_plugin_completion_record_id,
    stage1_complete_record_id,
    stage2_complete_record_id,
)


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def put_new(self, key: str, value: dict[str, Any]) -> None:
        if key in self.data:
            raise FileExistsError(key)
        self.data[key] = dict(value)

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = dict(value)


class _Logger:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []

    def log(self, name: str, payload: dict[str, Any]) -> None:
        self.rows.append((str(name), dict(payload)))


class Stage1RetentionMarkerTests(unittest.TestCase):
    def _seed_uia_docs(self, metadata: _MetadataStore, *, frame_id: str, snapshot_id: str, content_hash: str) -> None:
        for record_type, record_id in _frame_uia_expected_ids(snapshot_id).items():
            metadata.put(
                record_id,
                {
                    "record_type": record_type,
                    "run_id": "run_test",
                    "source_record_id": frame_id,
                    "uia_record_id": snapshot_id,
                    "uia_content_hash": content_hash,
                    "hwnd": "0x123",
                    "window_title": "Inbox - Outlook",
                    "window_pid": 4242,
                    "bboxes": [[0, 0, 1920, 1080]],
                },
            )

    def test_frame_marks_stage1_and_retention(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/1"
        uia_id = "run_test/evidence.uia.snapshot/1"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame.blob",
            "content_hash": "abc123",
            "uia_ref": {"record_id": uia_id, "content_hash": "uia123"},
            "input_ref": {"record_id": "run_test/evidence.input.batch/1"},
        }
        self._seed_uia_docs(metadata, frame_id=record_id, snapshot_id=uia_id, content_hash="uia123")
        result = mark_stage1_and_retention(metadata, record_id, payload, reason="idle_processed")
        self.assertTrue(result["stage1_complete"])
        self.assertEqual(result["stage1_record_id"], stage1_complete_record_id(record_id))
        self.assertEqual(result["retention_record_id"], retention_eligibility_record_id(record_id))
        marker = metadata.get(retention_eligibility_record_id(record_id), {})
        self.assertTrue(bool(marker.get("stage1_contract_validated", False)))
        self.assertFalse(bool(marker.get("quarantine_pending", False)))

    def test_legacy_non_frame_still_marks_retention(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.segment/1"
        payload = {
            "record_type": "evidence.capture.segment",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
        }
        result = mark_stage1_and_retention(metadata, record_id, payload, reason="idle_processed")
        self.assertFalse(result["stage1_complete"])
        self.assertIsNone(result["stage1_record_id"])
        self.assertEqual(result["retention_record_id"], retention_eligibility_record_id(record_id))

    def test_incomplete_frame_does_not_mark_retention(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/2"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            # Missing content_hash/uia_ref/input_ref => incomplete Stage1.
            "blob_path": "media/rid_frame_2.blob",
        }
        result = mark_stage1_and_retention(metadata, record_id, payload, reason="idle_processed")
        self.assertFalse(result["stage1_complete"])
        self.assertIsNone(result["retention_record_id"])
        marker_id = retention_eligibility_record_id(record_id)
        self.assertIsNone(metadata.get(marker_id))

    def test_frame_without_uia_docs_blocks_retention_until_retry(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/3"
        uia_id = "run_test/evidence.uia.snapshot/3"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame_3.blob",
            "content_hash": "abc777",
            "uia_ref": {"record_id": uia_id, "content_hash": "uia777"},
            "input_ref": {"record_id": "run_test/evidence.input.batch/3"},
        }

        first = mark_stage1_and_retention(metadata, record_id, payload, reason="idle_processed")
        self.assertTrue(first["stage1_complete"])
        marker_id = retention_eligibility_record_id(record_id)
        self.assertIsNone(metadata.get(marker_id))
        self.assertIsNone(first["retention_record_id"])

        # Simulate retry after UIA docs are materialized by Stage1.
        self._seed_uia_docs(metadata, frame_id=record_id, snapshot_id=uia_id, content_hash="uia777")
        second = mark_stage1_and_retention(metadata, record_id, payload, reason="idle_processed")
        self.assertTrue(second["stage1_complete"])
        self.assertEqual(second["stage1_record_id"], first["stage1_record_id"])
        self.assertEqual(second["retention_record_id"], marker_id)
        marker_after = metadata.get(marker_id, {})
        self.assertTrue(bool(marker_after.get("stage1_contract_validated", False)))
        self.assertFalse(bool(marker_after.get("quarantine_pending", False)))

    def test_stage1_write_error_is_logged(self) -> None:
        class _WriteErrorMetadata(_MetadataStore):
            def put_new(self, key: str, value: dict[str, Any]) -> None:
                raise RuntimeError(f"boom:{key}")

        metadata = _WriteErrorMetadata()
        logger = _Logger()
        record_id = "run_test/evidence.capture.frame/4"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame_4.blob",
            "content_hash": "abc444",
            "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/4", "content_hash": "uia444"},
            "input_ref": {"record_id": "run_test/evidence.input.batch/4"},
        }
        stage1_id, inserted = mark_stage1_complete(metadata, record_id, payload, logger=logger)
        self.assertIsNone(stage1_id)
        self.assertFalse(inserted)
        names = [name for name, _payload in logger.rows]
        self.assertIn("ingest.stage1.complete.write_error", names)

    def test_retention_write_error_is_logged(self) -> None:
        class _WriteErrorMetadata(_MetadataStore):
            def put_new(self, key: str, value: dict[str, Any]) -> None:
                raise RuntimeError(f"boom:{key}")

        metadata = _WriteErrorMetadata()
        logger = _Logger()
        record_id = "run_test/evidence.capture.frame/5"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame_5.blob",
            "content_hash": "abc555",
        }
        rid = mark_evidence_retention_eligible(metadata, record_id, payload, logger=logger)
        self.assertIsNone(rid)
        names = [name for name, _payload in logger.rows]
        self.assertIn("storage.retention.eligible.write_error", names)

    def test_stage2_marker_written_and_complete_when_projection_ok(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/6"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame_6.blob",
            "content_hash": "abc666",
            "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/6", "content_hash": "uia666"},
            "input_ref": {"record_id": "run_test/evidence.input.batch/6"},
        }
        rid, inserted = mark_stage2_complete(
            metadata,
            record_id,
            payload,
            projection={"ok": True, "generated_docs": 2, "inserted_docs": 2, "generated_states": 1, "inserted_states": 1, "errors": 0},
            reason="idle_processed",
        )
        self.assertTrue(inserted)
        self.assertEqual(rid, stage2_complete_record_id(record_id))
        row = metadata.get(rid, {})
        self.assertTrue(bool(row.get("complete", False)))
        self.assertEqual(int(row.get("generated_states", 0) or 0), 1)
        self.assertEqual(int(row.get("inserted_docs", 0) or 0), 2)

    def test_stage2_marker_is_incomplete_when_projection_errors(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/7"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame_7.blob",
            "content_hash": "abc777",
            "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/7", "content_hash": "uia777"},
            "input_ref": {"record_id": "run_test/evidence.input.batch/7"},
        }
        rid, inserted = mark_stage2_complete(
            metadata,
            record_id,
            payload,
            projection={"ok": False, "generated_docs": 0, "inserted_docs": 0, "generated_states": 1, "inserted_states": 0, "errors": 1},
            reason="idle_processed",
        )
        self.assertTrue(inserted)
        self.assertEqual(rid, stage2_complete_record_id(record_id))
        row = metadata.get(rid, {})
        self.assertFalse(bool(row.get("complete", True)))

    def test_stage1_plugin_completion_marker_writes_and_is_idempotent(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/8"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
        }
        rid, inserted = mark_stage1_plugin_completion(
            metadata,
            record_id,
            payload,
            stage1_complete=True,
            retention_eligible=True,
            retention_missing=False,
            uia_required=True,
            uia_ok=True,
            obs_uia_inserted=3,
            stage2_projection_ok=True,
            stage2_projection_errors=0,
            stage2_complete=True,
        )
        self.assertTrue(inserted)
        self.assertEqual(rid, stage1_plugin_completion_record_id(record_id))
        row = metadata.get(rid, {})
        self.assertTrue(bool(row.get("complete", False)))
        self.assertEqual(int(row.get("obs_uia_inserted", 0) or 0), 3)

        rid2, inserted2 = mark_stage1_plugin_completion(
            metadata,
            record_id,
            payload,
            stage1_complete=True,
            retention_eligible=True,
            retention_missing=False,
            uia_required=True,
            uia_ok=True,
            obs_uia_inserted=3,
            stage2_projection_ok=True,
            stage2_projection_errors=0,
            stage2_complete=True,
        )
        self.assertEqual(rid2, rid)
        self.assertFalse(inserted2)

    def test_stage1_plugin_completion_incomplete_when_uia_required_missing(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/9"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
        }
        rid, inserted = mark_stage1_plugin_completion(
            metadata,
            record_id,
            payload,
            stage1_complete=False,
            retention_eligible=False,
            retention_missing=True,
            uia_required=True,
            uia_ok=False,
            uia_reason="snapshot_missing",
            obs_uia_inserted=0,
            stage2_projection_ok=False,
            stage2_projection_errors=1,
            stage2_complete=False,
        )
        self.assertTrue(inserted)
        row = metadata.get(rid, {})
        self.assertFalse(bool(row.get("complete", True)))
        self.assertEqual(str(row.get("uia_reason") or ""), "snapshot_missing")


if __name__ == "__main__":
    unittest.main()
