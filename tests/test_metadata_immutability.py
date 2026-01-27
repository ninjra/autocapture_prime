import unittest

from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from plugins.builtin.storage_memory.plugin import InMemoryStore


class MetadataImmutabilityTests(unittest.TestCase):
    def test_put_replace_blocks_evidence(self) -> None:
        store = InMemoryStore()
        meta = ImmutableMetadataStore(store)
        meta.put_new(
            "run1/segment/0",
            {"record_type": "evidence.capture.segment", "run_id": "run1", "content_hash": "hash"},
        )
        with self.assertRaises(RuntimeError):
            meta.put_replace(
                "run1/segment/0",
                {"record_type": "evidence.capture.segment", "run_id": "run1", "content_hash": "hash"},
            )

    def test_delete_allows_derived_only(self) -> None:
        store = InMemoryStore()
        meta = ImmutableMetadataStore(store)
        meta.put_new(
            "run1/segment/0",
            {"record_type": "evidence.capture.segment", "run_id": "run1", "content_hash": "hash"},
        )
        meta.put_new("run1/derived.text.ocr/abc", {"record_type": "derived.text.ocr"})
        self.assertTrue(meta.delete("run1/derived.text.ocr/abc"))
        with self.assertRaises(RuntimeError):
            meta.delete("run1/segment/0")


if __name__ == "__main__":
    unittest.main()
