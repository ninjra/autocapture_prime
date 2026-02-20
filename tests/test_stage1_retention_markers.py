from __future__ import annotations

import unittest
from typing import Any

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import mark_stage1_and_retention, stage1_complete_record_id


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


class Stage1RetentionMarkerTests(unittest.TestCase):
    def test_frame_marks_stage1_and_retention(self) -> None:
        metadata = _MetadataStore()
        record_id = "run_test/evidence.capture.frame/1"
        payload = {
            "record_type": "evidence.capture.frame",
            "run_id": "run_test",
            "ts_utc": "2026-02-20T00:00:00Z",
            "blob_path": "media/rid_frame.blob",
            "content_hash": "abc123",
            "uia_ref": {"record_id": "run_test/evidence.uia.snapshot/1", "content_hash": "uia123"},
            "input_ref": {"record_id": "run_test/evidence.input.batch/1"},
        }
        result = mark_stage1_and_retention(metadata, record_id, payload, reason="idle_processed")
        self.assertTrue(result["stage1_complete"])
        self.assertEqual(result["stage1_record_id"], stage1_complete_record_id(record_id))
        self.assertEqual(result["retention_record_id"], retention_eligibility_record_id(record_id))

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


if __name__ == "__main__":
    unittest.main()
