import hashlib
import tempfile
import unittest
from pathlib import Path

from autocapture.pillars.citable import verify_anchors, verify_evidence, verify_ledger
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.anchor_basic.plugin import AnchorWriter
from plugins.builtin.ledger_basic.plugin import LedgerWriter


class _MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def put(self, key: str, value: object) -> None:
        self._data[key] = value

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def keys(self) -> list[str]:
        return list(self._data.keys())


class VerifyIntegrityTests(unittest.TestCase):
    def test_verify_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = PluginContext(
                config={"storage": {"data_dir": tmp}, "runtime": {"run_id": "run1", "timezone": "UTC"}},
                get_capability=lambda _k: None,
                logger=lambda _m: None,
            )
            ledger = LedgerWriter("ledger", ctx)
            entry = {
                "record_type": "ledger.entry",
                "schema_version": 1,
                "entry_id": "e1",
                "ts_utc": "2025-01-01T00:00:00Z",
                "stage": "capture",
                "inputs": [],
                "outputs": ["e1"],
                "policy_snapshot_hash": "hash",
            }
            ledger.append(entry)
            path = Path(tmp) / "ledger.ndjson"
            ok, errors = verify_ledger(path)
            self.assertTrue(ok)
            self.assertEqual(errors, [])
            tampered = path.read_text(encoding="utf-8").replace("capture", "captureX")
            path.write_text(tampered, encoding="utf-8")
            ok, errors = verify_ledger(path)
            self.assertFalse(ok)
            self.assertTrue(errors)

    def test_verify_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = Path(tmp) / "anchors.ndjson"
            keyring = KeyRing.load(str(Path(tmp) / "keyring.json"))
            ctx = PluginContext(
                config={"storage": {"anchor": {"path": str(anchor_path), "use_dpapi": False}}},
                get_capability=lambda name: keyring if name == "storage.keyring" else None,
                logger=lambda _m: None,
            )
            anchor = AnchorWriter("anchor", ctx)
            anchor.anchor("ledger_head")
            ok, errors = verify_anchors(anchor_path, keyring)
            self.assertTrue(ok)
            self.assertEqual(errors, [])
            tampered = anchor_path.read_text(encoding="utf-8").replace("ledger_head", "ledger_x")
            anchor_path.write_text(tampered, encoding="utf-8")
            ok, errors = verify_anchors(anchor_path, keyring)
            self.assertFalse(ok)
            self.assertTrue(errors)

    def test_verify_evidence(self) -> None:
        metadata = _MemoryStore()
        media = _MemoryStore()
        data = b"evidence-bytes"
        media.put("ev1", data)
        record = {
            "record_type": "evidence.segment",
            "run_id": "run1",
            "content_hash": hashlib.sha256(data).hexdigest(),
        }
        record["payload_hash"] = sha256_canonical({k: v for k, v in record.items() if k != "payload_hash"})
        metadata.put("ev1", record)
        ok, errors = verify_evidence(metadata, media)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        record["content_hash"] = "bad"
        metadata.put("ev1", record)
        ok, errors = verify_evidence(metadata, media)
        self.assertFalse(ok)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
