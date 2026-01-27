import unittest

from autocapture.core.hashing import normalize_text
from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    derivation_edge_id,
)


class DerivedRecordTests(unittest.TestCase):
    def test_build_text_record_contains_identity_and_hashes(self) -> None:
        source = {"run_id": "run1", "ts_utc": "2026-01-01T00:00:00+00:00"}
        config = {"models": {"ocr_path": "models/ocr.onnx"}}
        raw_text = "Hello   world\n"
        record = build_text_record(
            kind="ocr",
            text=raw_text,
            source_id="run1/segment/0",
            source_record=source,
            provider_id="builtin.ocr",
            config=config,
            ts_utc="2026-01-01T00:00:00+00:00",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["record_type"], "derived.text.ocr")
        self.assertEqual(record["model_id"], "models/ocr.onnx")
        self.assertIn("model_digest", record)
        self.assertIn("content_hash", record)
        self.assertIn("payload_hash", record)
        self.assertEqual(record["text_normalized"], normalize_text(raw_text))

    def test_derivation_edge_ids(self) -> None:
        edge_id = derivation_edge_id("run1", "run1/segment/0", "run1/derived/0")
        self.assertTrue(edge_id.startswith("run1/derived.edge/"))
        edge = build_derivation_edge(
            run_id="run1",
            parent_id="run1/segment/0",
            child_id="run1/derived/0",
            relation_type="derived_from",
            span_ref={"kind": "time", "source_id": "run1/segment/0"},
            method="ocr",
        )
        self.assertEqual(edge["record_type"], "derived.graph.edge")
        self.assertIn("content_hash", edge)


if __name__ == "__main__":
    unittest.main()
