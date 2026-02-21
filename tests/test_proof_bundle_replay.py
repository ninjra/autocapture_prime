import tempfile
import unittest
from pathlib import Path

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.proof_bundle import export_proof_bundle
from autocapture_nx.kernel.replay import replay_bundle
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.anchor_basic.plugin import AnchorWriter
from plugins.builtin.ledger_basic.plugin import LedgerWriter
from plugins.builtin.storage_memory.plugin import StorageMemoryPlugin


class ProofBundleReplayTests(unittest.TestCase):
    def test_export_and_replay_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = Path(tmp) / "anchors.ndjson"
            bundle_path = Path(tmp) / "bundle.zip"
            config = {
                "storage": {"data_dir": tmp, "anchor": {"path": str(anchor_path), "use_dpapi": False}}
            }
            ctx = PluginContext(config=config, get_capability=lambda _n: None, logger=lambda _m: None)
            storage = StorageMemoryPlugin("storage.memory", ctx)
            caps = storage.capabilities()
            metadata = caps["storage.metadata"]
            media = caps["storage.media"]

            evidence_id = "run1/segment/0"
            evidence_text = "evidence payload"
            evidence_hash = hash_text(normalize_text(evidence_text))
            metadata.put(
                evidence_id,
                {
                    "schema_version": 1,
                    "record_type": "evidence.capture.segment",
                    "run_id": "run1",
                    "segment_id": "seg0",
                    "ts_start_utc": "2026-01-01T00:00:00+00:00",
                    "ts_end_utc": "2026-01-01T00:00:10+00:00",
                    "ts_utc": "2026-01-01T00:00:00+00:00",
                    "width": 1,
                    "height": 1,
                    "container": {"type": "zip"},
                    "content_hash": evidence_hash,
                    "text": evidence_text,
                },
            )
            media.put(evidence_id, b"blob-data")

            ledger = LedgerWriter("ledger", ctx)
            ledger_hash = ledger.append(
                {
                    "record_type": "ledger.entry",
                    "schema_version": 1,
                    "entry_id": "run1/ledger/0",
                    "ts_utc": "2026-01-01T00:00:00+00:00",
                    "stage": "query.execute",
                    "inputs": [evidence_id],
                    "outputs": [evidence_id],
                    "policy_snapshot_hash": "policy",
                    "payload": {
                        "event": "query.execute",
                        "retrieval_trace": [
                            {"tier": "LEXICAL", "index": {"version": 1, "digest": "deadbeef"}}
                        ],
                    },
                }
            )
            anchor = AnchorWriter("anchor", ctx)
            anchor_record = anchor.anchor(ledger_hash)
            anchor_ref = {
                "anchor_seq": anchor_record.get("anchor_seq"),
                "ledger_head_hash": anchor_record.get("ledger_head_hash"),
            }
            citations = [
                {
                    "schema_version": 1,
                    "locator": {"kind": "record", "record_id": evidence_id, "record_hash": evidence_hash},
                    "span_id": evidence_id,
                    "evidence_id": evidence_id,
                    "evidence_hash": evidence_hash,
                    "derived_id": None,
                    "derived_hash": None,
                    "span_kind": "record",
                    "ledger_head": ledger_hash,
                    "anchor_ref": anchor_ref,
                    "source": "local",
                    "offset_start": 0,
                    "offset_end": 0,
                }
            ]

            report = export_proof_bundle(
                metadata=metadata,
                media=media,
                keyring=None,
                ledger_path=Path(tmp) / "ledger.ndjson",
                anchor_path=anchor_path,
                output_path=bundle_path,
                evidence_ids=[evidence_id],
                citations=citations,
            )
            self.assertTrue(bundle_path.exists())
            self.assertTrue(report.ok)

            replay = replay_bundle(bundle_path)
            self.assertTrue(replay.ok)


if __name__ == "__main__":
    unittest.main()
