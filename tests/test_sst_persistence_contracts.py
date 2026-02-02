import unittest

from autocapture_nx.processing.sst.persist import SSTPersistence, config_hash


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def get(self, record_id: str, default=None):
        return self.data.get(record_id, default)

    def put_new(self, record_id: str, value: dict) -> None:
        if record_id in self.data:
            raise FileExistsError(record_id)
        self.data[record_id] = value


class SSTPersistenceContractTests(unittest.TestCase):
    def test_persist_frame_artifact_identity(self) -> None:
        metadata = _MetadataStore()
        cfg_hash = config_hash({"redact_enabled": True})
        persistence = SSTPersistence(
            metadata=metadata,
            event_builder=None,
            index_text=lambda _doc_id, _text: None,
            extractor_id="test.sst",
            extractor_version="1.0.0",
            config_hash=cfg_hash,
            schema_version=1,
        )
        record_id = "run1/segment/0"
        stats = persistence.persist_frame(
            run_id="run1",
            record_id=record_id,
            ts_ms=1,
            width=320,
            height=200,
            image_sha256="img",
            phash="phash",
            boundary=False,
            boundary_reason="",
            phash_distance=0,
            diff_score_bp=0,
        )
        self.assertEqual(stats.derived_records, 1)
        self.assertEqual(len(stats.derived_ids), 1)
        derived_id = stats.derived_ids[0]
        payload = metadata.get(derived_id)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("artifact_id"), derived_id)
        self.assertEqual(payload.get("record_type"), "derived.sst.frame")
        extractor = payload.get("extractor", {})
        self.assertEqual(extractor.get("id"), "test.sst")
        self.assertEqual(extractor.get("version"), "1.0.0")
        provenance = payload.get("provenance", {})
        self.assertIn(record_id, provenance.get("frame_ids", ()))

        stats2 = persistence.persist_frame(
            run_id="run1",
            record_id=record_id,
            ts_ms=2,
            width=320,
            height=200,
            image_sha256="img",
            phash="phash",
            boundary=False,
            boundary_reason="",
            phash_distance=0,
            diff_score_bp=0,
        )
        self.assertEqual(stats2.derived_records, 0)
        self.assertEqual(len(metadata.data), 1)


if __name__ == "__main__":
    unittest.main()
