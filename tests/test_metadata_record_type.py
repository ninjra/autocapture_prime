import unittest

from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore


class _Store:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put(self, key, value):
        self.data[key] = value

    def keys(self):
        return list(self.data.keys())


class MetadataRecordTypeTests(unittest.TestCase):
    def test_record_type_required(self) -> None:
        store = ImmutableMetadataStore(_Store())
        with self.assertRaises(ValueError):
            store.put("rec", {"value": 1})
        store.put("rec", {"record_type": "derived.test", "value": 1})
        self.assertEqual(store.get("rec")["value"], 1)

    def test_evidence_requires_run_id_and_hash(self) -> None:
        store = ImmutableMetadataStore(_Store())
        with self.assertRaises(ValueError):
            store.put("rec1", {"record_type": "evidence.capture.segment", "content_hash": "hash"})
        with self.assertRaises(ValueError):
            store.put("rec2", {"record_type": "evidence.capture.segment", "run_id": "run1"})
        store.put(
            "rec3",
            {"record_type": "evidence.capture.segment", "run_id": "run1", "content_hash": "hash"},
        )
        self.assertEqual(store.get("rec3")["run_id"], "run1")


if __name__ == "__main__":
    unittest.main()
