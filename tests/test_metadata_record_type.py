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
        store.put(
            "rec",
            {"schema_version": 1, "record_type": "derived.test", "run_id": "run1", "content_hash": "hash", "value": 1},
        )
        self.assertEqual(store.get("rec")["value"], 1)

    def test_evidence_requires_run_id_and_hash(self) -> None:
        store = ImmutableMetadataStore(_Store())
        base = {
            "schema_version": 1,
            "record_type": "evidence.capture.segment",
            "segment_id": "seg0",
            "ts_start_utc": "2026-01-01T00:00:00+00:00",
            "ts_end_utc": "2026-01-01T00:00:10+00:00",
            "width": 1,
            "height": 1,
            "container": {"type": "zip"},
        }
        with self.assertRaises(ValueError):
            store.put("rec1", {**base, "content_hash": "hash"})
        with self.assertRaises(ValueError):
            store.put("rec2", {**base, "run_id": "run1"})
        store.put(
            "rec3",
            {**base, "run_id": "run1", "content_hash": "hash"},
        )
        self.assertEqual(store.get("rec3")["run_id"], "run1")


if __name__ == "__main__":
    unittest.main()
