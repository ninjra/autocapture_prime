import json
import tempfile
import zipfile
from pathlib import Path
import unittest

from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.kernel.proof_bundle import export_proof_bundle, verify_proof_bundle
from autocapture_nx.kernel.replay import replay_bundle


class _Store:
    def __init__(self, mapping):
        self._m = dict(mapping)

    def get(self, key, default=None):
        return self._m.get(key, default)

    def keys(self):
        return list(self._m.keys())


class ProofBundleVerifyTests(unittest.TestCase):
    def test_verify_detects_missing_files_and_replay_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            keyring = KeyRing.load(str(root / "keyring.json"), backend="portable_file")
            evidence_id = "run_test/evidence.capture.segment/seg1"
            metadata = _Store(
                {
                    evidence_id: {
                        "record_type": "evidence.capture.segment",
                        "run_id": "run_test",
                        "ts_utc": "2026-02-07T00:00:00Z",
                        "content_hash": "deadbeef",
                    }
                }
            )
            media = _Store({})
            ledger_path = root / "ledger.ndjson"
            anchor_path = root / "anchors.ndjson"
            ledger_path.write_text("", encoding="utf-8")
            anchor_path.write_text("", encoding="utf-8")
            out = root / "bundle.zip"
            report = export_proof_bundle(
                metadata=metadata,
                media=media,
                keyring=keyring,
                ledger_path=ledger_path,
                anchor_path=anchor_path,
                output_path=out,
                evidence_ids=[evidence_id],
                citations=None,
            )
            self.assertTrue(report.ok, msg=report.errors)

            ok = verify_proof_bundle(out, keyring=keyring)
            self.assertTrue(ok.get("ok"), msg=ok)

            # Tamper a listed file (hash mismatch).
            tampered = root / "bundle_tampered_file.zip"
            with zipfile.ZipFile(out, "r") as src, zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename == "verification.json":
                        obj = json.loads(data.decode("utf-8"))
                        obj["errors"] = ["tampered"]
                        data = json.dumps(obj, sort_keys=True, indent=2).encode("utf-8")
                    dst.writestr(info, data)
            bad = verify_proof_bundle(tampered, keyring=keyring)
            self.assertFalse(bad.get("ok"))
            self.assertIn("bundle_file_sha256_mismatch", str(bad.get("error")))

            replay = replay_bundle(tampered, keyring=keyring)
            self.assertFalse(replay.ok)
            self.assertTrue(any("bundle_signature_invalid" in err for err in replay.errors))


if __name__ == "__main__":
    unittest.main()

