import unittest
from datetime import datetime, timedelta, timezone

from autocapture.storage.retention import apply_evidence_retention
from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from plugins.builtin.storage_memory.plugin import InMemoryStore


class StorageRetentionTests(unittest.TestCase):
    def test_retention_disabled_by_policy(self) -> None:
        metadata = ImmutableMetadataStore(InMemoryStore())
        media = InMemoryStore()
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=2)).isoformat()
        new_ts = now.isoformat()
        old_id = "run1/frame/0"
        new_id = "run1/frame/1"
        metadata.put_new(
            old_id,
            {
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": old_ts,
                "content_hash": "abc",
            },
        )
        metadata.put_new(
            new_id,
            {
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": new_ts,
                "content_hash": "def",
            },
        )
        media.put_new(old_id, b"old", ts_utc=old_ts)
        media.put_new(new_id, b"new", ts_utc=new_ts)
        config = {
            "storage": {
                "retention": {
                    "evidence": "1d",
                    "max_delete_per_run": 10,
                }
            }
        }
        result = apply_evidence_retention(metadata, media, config, dry_run=False)
        self.assertIsNone(result)
        self.assertEqual(media.get(old_id), b"old")
        self.assertEqual(media.get(new_id), b"new")
        self.assertIsNotNone(metadata.get(old_id))
        self.assertIsNotNone(metadata.get(new_id))

    def test_retention_disabled_returns_none(self) -> None:
        metadata = ImmutableMetadataStore(InMemoryStore())
        media = InMemoryStore()
        config = {"storage": {"retention": {"evidence": "infinite"}}}
        result = apply_evidence_retention(metadata, media, config, dry_run=False)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
