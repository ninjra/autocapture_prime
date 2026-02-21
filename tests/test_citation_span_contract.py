import tempfile
import unittest
from pathlib import Path

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.anchor_basic.plugin import AnchorWriter
from plugins.builtin.citation_basic.plugin import CitationValidator
from plugins.builtin.ledger_basic.plugin import LedgerWriter


class _MetaStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def put(self, record_id: str, value: dict) -> None:
        self._data[record_id] = value

    def get(self, record_id: str, default=None):
        return self._data.get(record_id, default)


class CitationSpanContractTests(unittest.TestCase):
    def test_text_span_locator_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = Path(tmp) / "anchors.ndjson"
            config = {"storage": {"data_dir": tmp, "anchor": {"path": str(anchor_path), "use_dpapi": False}}}
            base_ctx = PluginContext(config=config, get_capability=lambda _n: None, logger=lambda _m: None)
            ledger = LedgerWriter("ledger", base_ctx)
            ledger_head = ledger.append(
                {
                    "record_type": "ledger.entry",
                    "schema_version": 1,
                    "entry_id": "run1/ledger/0",
                    "ts_utc": "2026-01-01T00:00:00+00:00",
                    "stage": "query.execute",
                    "inputs": [],
                    "outputs": [],
                    "policy_snapshot_hash": "policy",
                    "payload": {"event": "query.execute"},
                }
            )
            anchor = AnchorWriter("anchor", base_ctx)
            anchor_record = anchor.anchor(ledger_head)
            anchor_ref = {"anchor_seq": anchor_record.get("anchor_seq"), "ledger_head_hash": anchor_record.get("ledger_head_hash")}

            store = _MetaStore()
            evidence_id = "run1/segment/0"
            evidence_text = "evidence"
            evidence_hash = hash_text(normalize_text(evidence_text))
            store.put(evidence_id, {"record_type": "evidence.capture.segment", "content_hash": evidence_hash, "text": evidence_text})

            derived_id = "run1/derived/0"
            derived_text = "hello world"
            derived_hash = hash_text(normalize_text(derived_text))
            store.put(derived_id, {"record_type": "derived.text.ocr", "content_hash": derived_hash, "source_id": evidence_id, "text": derived_text})

            def get_capability(name: str):
                if name == "storage.metadata":
                    return store
                raise KeyError(name)

            validator = CitationValidator("cit", PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None))

            good = [
                {
                    "schema_version": 1,
                    "locator": {
                        "kind": "text_offsets",
                        "record_id": derived_id,
                        "record_hash": derived_hash,
                        "offset_start": 0,
                        "offset_end": 5,
                        "span_sha256": sha256_text(derived_text[0:5]),
                    },
                    "span_id": evidence_id,
                    "evidence_id": evidence_id,
                    "evidence_hash": evidence_hash,
                    "derived_id": derived_id,
                    "derived_hash": derived_hash,
                    "span_kind": "text",
                    "ledger_head": ledger_head,
                    "anchor_ref": anchor_ref,
                    "source": "local",
                    "offset_start": 0,
                    "offset_end": 5,
                }
            ]
            self.assertTrue(validator.validate(good))

            bad_missing = [dict(good[0])]
            bad_missing[0].pop("locator", None)
            with self.assertRaises(ValueError):
                validator.validate(bad_missing)

            bad_offsets = [dict(good[0])]
            bad_offsets[0]["locator"] = dict(bad_offsets[0]["locator"])
            bad_offsets[0]["locator"]["offset_end"] = 6
            with self.assertRaises(ValueError):
                validator.validate(bad_offsets)

            bad_hash = [dict(good[0])]
            bad_hash[0]["locator"] = dict(bad_hash[0]["locator"])
            bad_hash[0]["locator"]["span_sha256"] = "bad"
            with self.assertRaises(ValueError):
                validator.validate(bad_hash)


if __name__ == "__main__":
    unittest.main()

