import hashlib
import tempfile
import unittest
from pathlib import Path

from autocapture.pillars.citable import integrity_scan
from autocapture.pillars.citable import Ledger
from autocapture_nx.kernel.hashing import sha256_canonical


class _MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def put(self, key: str, value: object) -> None:
        self._data[key] = value

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def keys(self) -> list[str]:
        return list(self._data.keys())


class IntegrityScanTests(unittest.TestCase):
    def test_integrity_scan_ok_and_fails_on_ref_break(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_path = tmp_path / "ledger.ndjson"
            anchor_path = tmp_path / "anchors.ndjson"

            # Minimal valid ledger chain (one entry), using the canonical hasher.
            ledger = Ledger(ledger_path)
            entry_hash = ledger.append(
                {
                    "record_type": "ledger.entry",
                    "schema_version": 1,
                    "entry_id": "e1",
                    "ts_utc": "2026-01-01T00:00:00+00:00",
                    "stage": "capture",
                    "inputs": [],
                    "outputs": ["ev1"],
                    "policy_snapshot_hash": "policy",
                }
            )

            # Minimal anchors file (no HMAC signature expected).
            import json

            anchor_path.write_text(json.dumps({"anchor_seq": 1, "ledger_head_hash": entry_hash}) + "\n", encoding="utf-8")

            metadata = _MemoryStore()
            media = _MemoryStore()
            blob = b"blob"
            media.put("ev1", blob)
            record = {
                "record_type": "evidence.capture.segment",
                "run_id": "run1",
                "content_hash": hashlib.sha256(blob).hexdigest(),
            }
            record["payload_hash"] = sha256_canonical({k: v for k, v in record.items() if k != "payload_hash"})
            metadata.put("ev1", record)
            metadata.put("d1", {"record_type": "derived.text.ocr", "source_id": "ev1", "content_hash": "x"})

            report = integrity_scan(ledger_path=ledger_path, anchor_path=anchor_path, metadata=metadata, media=media, keyring=None)
            self.assertTrue(report["ok"])

            metadata.put("d1", {"record_type": "derived.text.ocr", "source_id": "missing", "content_hash": "x"})
            report2 = integrity_scan(ledger_path=ledger_path, anchor_path=anchor_path, metadata=metadata, media=media, keyring=None)
            self.assertFalse(report2["ok"])


if __name__ == "__main__":
    unittest.main()
