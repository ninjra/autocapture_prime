import unittest

from autocapture_nx.kernel.query import run_query


class _Parser:
    def parse(self, _text: str):
        return {"time_window": None}


class _Retrieval:
    def __init__(self, record_id: str, derived_id: str):
        self._record_id = record_id
        self._derived_id = derived_id

    def search(self, _text: str, *, time_window=None):
        _ = time_window
        return [{"record_id": self._record_id, "derived_id": self._derived_id}]

    def trace(self):
        return [{"k": 1}]


class _Answer:
    def build(self, claims):
        return {"state": "ok", "claims": claims, "errors": []}


class _EventBuilder:
    run_id = "run_test"

    def ledger_entry(self, *_args, **_kwargs):
        return "ledger_head_test"

    def last_anchor(self):
        return "anchor_ref_test"


class _Meta:
    def __init__(self, mapping):
        self._m = dict(mapping)

    def get(self, key, default=None):
        return self._m.get(key, default)

    def keys(self):
        return list(self._m.keys())


class _System:
    def __init__(self, config, caps):
        self.config = config
        self._caps = dict(caps)

    def get(self, name):
        return self._caps[name]

    def has(self, name):
        return name in self._caps


class QueryProvenanceHeaderTests(unittest.TestCase):
    def test_query_includes_provenance_header(self) -> None:
        evidence_id = "run_test/evidence.capture.segment/seg1"
        derived_id = "run_test/derived.text.ocr/provider/seg1"
        metadata = _Meta(
            {
                evidence_id: {
                    "record_type": "evidence.capture.segment",
                    "content_hash": "hash_e",
                    "ts_utc": "2026-02-07T00:00:00Z",
                },
                derived_id: {
                    "record_type": "derived.text.ocr",
                    "text": "HELLO",
                    "span_ref": {"kind": "text", "note": "test"},
                    "content_hash": "hash_d",
                },
            }
        )
        system = _System(
            config={
                "runtime": {"run_id": "run_test"},
                "storage": {"data_dir": "/tmp/data"},
                "processing": {"state_layer": {"query_enabled": False}, "on_query": {"allow_decode_extract": False}},
                "plugins": {"locks": {"lockfile": "config/plugin_locks.json"}},
            },
            caps={
                "time.intent_parser": _Parser(),
                "retrieval.strategy": _Retrieval(evidence_id, derived_id),
                "answer.builder": _Answer(),
                "storage.metadata": metadata,
                "event.builder": _EventBuilder(),
            },
        )
        result = run_query(system, "hello world")
        prov = result.get("provenance", {})
        self.assertEqual(prov.get("schema_version"), 1)
        self.assertEqual(prov.get("run_id"), "run_test")
        self.assertEqual(prov.get("query_ledger_head"), "ledger_head_test")
        self.assertEqual(prov.get("anchor_ref"), "anchor_ref_test")
        self.assertIn("generated_at_utc", prov)


if __name__ == "__main__":
    unittest.main()

