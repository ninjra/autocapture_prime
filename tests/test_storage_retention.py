import unittest
from datetime import datetime, timedelta, timezone

from autocapture.storage.retention import apply_evidence_retention, mark_evidence_retention_eligible, retention_eligibility_record_id
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
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": old_ts,
                "content_hash": "abc",
            },
        )
        metadata.put_new(
            new_id,
            {
                "schema_version": 1,
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

    def test_retention_processed_only_requires_eligibility_marker(self) -> None:
        metadata = ImmutableMetadataStore(InMemoryStore())
        media = InMemoryStore()
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=3)).isoformat()
        record_id = "run1/frame/0"
        record = {
            "schema_version": 1,
            "record_type": "evidence.capture.frame",
            "run_id": "run1",
            "ts_utc": old_ts,
            "content_hash": "abc",
            "content_type": "image/png",
        }
        metadata.put_new(record_id, dict(record))
        media.put_new(record_id, b"old", ts_utc=old_ts)
        config = {
            "storage": {
                "no_deletion_mode": False,
                "retention": {
                    "evidence": "1d",
                    "max_delete_per_run": 10,
                    "processed_only": True,
                    "images_only": True,
                },
            }
        }

        result_blocked = apply_evidence_retention(metadata, media, config, dry_run=False)
        self.assertIsNotNone(result_blocked)
        self.assertEqual(int(result_blocked.deleted), 0)
        self.assertEqual(media.get(record_id), b"old")

        legacy_marker_id = mark_evidence_retention_eligible(metadata, record_id, record, reason="legacy_test")
        self.assertEqual(legacy_marker_id, retention_eligibility_record_id(record_id))
        result_legacy_blocked = apply_evidence_retention(metadata, media, config, dry_run=False)
        self.assertIsNotNone(result_legacy_blocked)
        self.assertEqual(int(result_legacy_blocked.deleted), 0)
        self.assertEqual(media.get(record_id), b"old")

        marker_id = mark_evidence_retention_eligible(
            metadata,
            record_id,
            record,
            reason="test",
            stage1_contract_validated=True,
        )
        self.assertEqual(marker_id, retention_eligibility_record_id(record_id))
        self.assertIsNotNone(metadata.get(marker_id))

        result_allowed = apply_evidence_retention(metadata, media, config, dry_run=False)
        self.assertIsNotNone(result_allowed)
        self.assertEqual(int(result_allowed.deleted), 1)
        self.assertIsNone(media.get(record_id))


if __name__ == "__main__":
    unittest.main()
