import unittest

from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from autocapture_nx.kernel.hashing import sha256_canonical


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
        # Evidence-like records must include run_id, but do not need a caller-supplied
        # content_hash: the store normalizes payload_hash to satisfy the contract.
        store.put("rec2", {**base, "run_id": "run1"})
        rec2 = store.get("rec2")
        self.assertEqual(rec2["run_id"], "run1")
        self.assertIn("payload_hash", rec2)
        self.assertEqual(
            rec2["payload_hash"],
            sha256_canonical({k: v for k, v in rec2.items() if k != "payload_hash"}),
        )
        store.put(
            "rec3",
            {**base, "run_id": "run1", "content_hash": "hash"},
        )
        self.assertEqual(store.get("rec3")["run_id"], "run1")


if __name__ == "__main__":
    unittest.main()
