import unittest

from autocapture_nx.kernel.config import SchemaLiteValidator


class EvidenceSchemaTests(unittest.TestCase):
    def test_evidence_schema_accepts_known_types(self) -> None:
        validator = SchemaLiteValidator()
        schema = {
            "type": "object",
            "additionalProperties": True,
        }
        from pathlib import Path
        import json

        schema = json.loads(Path("contracts/evidence.schema.json").read_text(encoding="utf-8"))

        samples = [
            {
                "schema_version": 1,
                "record_type": "evidence.capture.segment",
                "run_id": "run1",
                "segment_id": "seg0",
                "ts_start_utc": "2026-01-01T00:00:00+00:00",
                "ts_end_utc": "2026-01-01T00:00:10+00:00",
                "width": 1,
                "height": 1,
                "container": {"type": "zip"},
                "content_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": "2026-01-01T00:00:00+00:00",
                "content_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "evidence.window.meta",
                "run_id": "run1",
                "ts_utc": "2026-01-01T00:00:00+00:00",
                "window": {"title": "App"},
                "content_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.text.ocr",
                "run_id": "run1",
                "text": "hello",
                "source_id": "run1/segment/0",
                "parent_evidence_id": "run1/segment/0",
                "span_ref": {"kind": "time", "source_id": "run1/segment/0"},
                "method": "ocr",
                "provider_id": "ocr.engine",
                "model_id": "ocr.engine",
                "model_digest": "digest",
                "payload_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.text.qa",
                "run_id": "run1",
                "text": "VDI time: 11:35 AM",
                "source_id": "run1/segment/0",
                "parent_evidence_id": "run1/segment/0",
                "span_ref": {"kind": "time", "source_id": "run1/segment/0"},
                "method": "qa",
                "provider_id": "qa.fixture",
                "model_id": "qa.fixture",
                "model_digest": "digest",
                "payload_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.input.summary",
                "run_id": "run1",
                "start_ts_utc": "2026-01-01T00:00:00+00:00",
                "end_ts_utc": "2026-01-01T00:00:10+00:00",
                "event_id": "evt1",
                "event_count": 1,
                "payload_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.cursor.sample",
                "run_id": "run1",
                "ts_utc": "2026-01-01T00:00:00+00:00",
                "cursor": {"x": 1, "y": 2},
                "payload_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.audio.segment",
                "run_id": "run1",
                "ts_utc": "2026-01-01T00:00:00+00:00",
                "encoding": "wav",
                "sample_rate": 44100,
                "channels": 2,
                "payload_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.graph.edge",
                "run_id": "run1",
                "parent_id": "run1/segment/0",
                "child_id": "run1/derived.text.ocr/0",
                "relation_type": "derived_from",
                "span_ref": {"kind": "time", "source_id": "run1/segment/0"},
                "method": "ocr",
                "content_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.sst.frame",
                "run_id": "run1",
                "artifact_id": "run1/derived.sst.frame/0",
                "kind": "FrameTrace",
                "created_ts_ms": 1,
                "extractor": {"id": "sst", "version": "1"},
                "provenance": {"frame_ids": ["run1/segment/0"]},
                "content_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.sst.text.extra",
                "run_id": "run1",
                "artifact_id": "run1/derived.sst.text.extra/0",
                "kind": "ScreenState",
                "created_ts_ms": 1,
                "extractor": {"id": "sst", "version": "1"},
                "provenance": {"frame_ids": ["run1/segment/0"]},
                "content_hash": "hash",
            },
            {
                "schema_version": 1,
                "record_type": "derived.test",
                "run_id": "run1",
                "payload_hash": "hash",
            },
        ]

        for sample in samples:
            validator.validate(schema, sample)


if __name__ == "__main__":
    unittest.main()
