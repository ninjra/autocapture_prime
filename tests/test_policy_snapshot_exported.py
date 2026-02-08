import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from autocapture_nx.kernel.proof_bundle import export_proof_bundle
from autocapture_nx.kernel.policy_snapshot import persist_policy_snapshot


class _DictStore:
    def __init__(self) -> None:
        self.data = {}

    def put_new(self, key: str, value):
        if key in self.data:
            raise FileExistsError(key)
        self.data[key] = value

    def put(self, key: str, value):
        self.data[key] = value

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def keys(self):
        return list(self.data.keys())


class _MediaStore:
    def __init__(self) -> None:
        self.data = {}

    def put(self, key: str, value: bytes, **_kwargs):
        self.data[key] = bytes(value)

    def get(self, key: str):
        return self.data.get(key, None)


def _write_minimal_ledger(path: Path, *, policy_snapshot_hash: str, evidence_id: str) -> None:
    # Match plugins/builtin/ledger_basic/plugin.py hashing contract.
    import hashlib
    from autocapture_nx.kernel.canonical_json import dumps

    payload = {
        "record_type": "ledger.entry",
        "schema_version": 1,
        "entry_id": "test",
        "ts_utc": "2026-02-08T00:00:00Z",
        "stage": "test",
        "inputs": [],
        "outputs": [evidence_id],
        "policy_snapshot_hash": policy_snapshot_hash,
        "payload": {"event": "test"},
        "prev_hash": None,
    }
    canonical = dumps(payload)
    entry_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload["entry_hash"] = entry_hash
    path.write_text(f"{dumps(payload)}\n", encoding="utf-8")


class PolicySnapshotExportTests(unittest.TestCase):
    def test_policy_snapshot_included_in_proof_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            ledger_path = data_dir / "ledger.ndjson"
            anchor_path = data_dir / "anchors.ndjson"
            anchor_path.write_text("", encoding="utf-8")

            metadata = _DictStore()
            media = _MediaStore()
            evidence_id = "evidence/test/0"
            evidence = {
                "record_type": "evidence.capture.segment",
                "run_id": "run",
                "ts_utc": "2026-02-08T00:00:00Z",
                "content_hash": "00" * 32,
            }
            metadata.put_new(evidence_id, evidence)
            media.put(evidence_id, b"blob")

            cfg = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            cfg.setdefault("storage", {})["data_dir"] = str(data_dir)
            snap = persist_policy_snapshot(config=cfg, data_dir=data_dir, metadata=metadata, ts_utc="2026-02-08T00:00:00Z")

            _write_minimal_ledger(ledger_path, policy_snapshot_hash=snap.snapshot_hash, evidence_id=evidence_id)

            out_zip = root / "proof.zip"
            report = export_proof_bundle(
                metadata=metadata,
                media=media,
                ledger_path=ledger_path,
                anchor_path=anchor_path,
                output_path=out_zip,
                evidence_ids=[evidence_id],
                citations=None,
            )
            self.assertTrue(report.ok)
            self.assertTrue(out_zip.exists())

            with zipfile.ZipFile(out_zip, "r") as zf:
                names = set(zf.namelist())
                policy_path = f"policy_snapshots/{snap.snapshot_hash}.json"
                self.assertIn(policy_path, names)
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                self.assertIn(snap.snapshot_hash, manifest.get("policy_snapshot_hashes", []))
                verification = json.loads(zf.read("verification.json").decode("utf-8"))
                self.assertTrue(verification.get("policy_snapshot", {}).get("ok"))


if __name__ == "__main__":
    unittest.main()

