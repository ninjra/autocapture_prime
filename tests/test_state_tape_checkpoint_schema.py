import unittest
from datetime import datetime, timezone

from autocapture_nx.kernel.evidence import validate_evidence_record
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.state_layer.processor import _normalize_counts


class StateTapeCheckpointSchemaTests(unittest.TestCase):
    def _checkpoint_payload(self) -> dict:
        payload = {
            "schema_version": 1,
            "record_type": "derived.state_tape.checkpoint",
            "run_id": "run",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "last_record_id": "run/derived.sst.state/abc",
            "processed_total": 3,
            "model_version": "v1",
            "config_hash": "cfg",
            "version_key": "v1:cfg",
        }
        payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
        return payload

    def test_checkpoint_payload_validates(self):
        payload = self._checkpoint_payload()
        validate_evidence_record(payload, "run/derived.state_tape.checkpoint/0")

    def test_checkpoint_requires_payload_hash(self):
        payload = self._checkpoint_payload()
        payload.pop("payload_hash", None)
        with self.assertRaises(ValueError):
            validate_evidence_record(payload, "run/derived.state_tape.checkpoint/0")

    def test_normalize_counts_handles_dict(self):
        spans, edges, evidence = _normalize_counts(
            {"spans_inserted": 2, "edges_inserted": 1, "evidence_inserted": 5}
        )
        self.assertEqual(spans, 2)
        self.assertEqual(edges, 1)
        self.assertEqual(evidence, 5)


if __name__ == "__main__":
    unittest.main()
