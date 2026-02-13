import unittest

from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from plugins.builtin.storage_memory.plugin import InMemoryStore


class MetadataImmutabilityTests(unittest.TestCase):
    def test_put_replace_blocks_evidence(self) -> None:
        store = InMemoryStore()
        meta = ImmutableMetadataStore(store)
        evidence = {
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
        }
        meta.put_new(
            "run1/segment/0",
            evidence,
        )
        with self.assertRaises(RuntimeError):
            meta.put_replace(
                "run1/segment/0",
                evidence,
            )

    def test_delete_allows_derived_only(self) -> None:
        store = InMemoryStore()
        meta = ImmutableMetadataStore(store)
        evidence = {
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
        }
        meta.put_new(
            "run1/segment/0",
            evidence,
        )
        meta.put_new(
            "run1/derived.text.ocr/abc",
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
                "content_hash": "hash",
            },
        )
        self.assertTrue(meta.delete("run1/derived.text.ocr/abc"))
        with self.assertRaises(RuntimeError):
            meta.delete("run1/segment/0")


if __name__ == "__main__":
    unittest.main()
