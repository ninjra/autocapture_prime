import unittest

from autocapture_nx.kernel.query import run_query


class _Parser:
    def parse(self, _text: str):
        return {"time_window": None}


class _Retrieval:
    def __init__(self, results):
        self._results = list(results)

    def search(self, _text: str, *, time_window=None):
        _ = time_window
        return list(self._results)

    def trace(self):
        return []


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


class QueryEvaluationFieldsTests(unittest.TestCase):
    def test_query_includes_evaluation_fields(self) -> None:
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
                "retrieval.strategy": _Retrieval([{"record_id": evidence_id, "derived_id": derived_id, "ts_utc": "2026-02-07T00:00:00Z"}]),
                "answer.builder": _Answer(),
                "storage.metadata": metadata,
                "event.builder": _EventBuilder(),
            },
        )
        result = run_query(system, "hello world")
        evaluation = result.get("evaluation", {})
        self.assertEqual(evaluation.get("schema_version"), 1)
        self.assertIn("coverage_ratio", evaluation)
        self.assertIn("missing_spans_count", evaluation)
        self.assertIn("blocked_extract", evaluation)
        self.assertIn("blocked_reason", evaluation)


if __name__ == "__main__":
    unittest.main()

