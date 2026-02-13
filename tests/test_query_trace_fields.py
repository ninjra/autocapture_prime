from __future__ import annotations

import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


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


class QueryTraceFieldsTests(unittest.TestCase):
    def test_run_query_writes_query_trace_and_metrics(self) -> None:
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
                    "text": "Inbox count is 4",
                    "span_ref": {"kind": "text", "note": "test"},
                    "content_hash": "hash_d",
                },
            }
        )
        system = _System(
            config={
                "runtime": {"run_id": "run_test"},
                "storage": {"data_dir": "/tmp/data"},
                "processing": {
                    "state_layer": {"query_enabled": False},
                    "on_query": {"allow_decode_extract": False},
                },
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
        with mock.patch.object(query_mod, "append_fact_line") as append_mock:
            out = query_mod.run_query(system, "how many inboxes do i have open")

        processing = out.get("processing", {})
        self.assertIsInstance(processing, dict)
        trace = processing.get("query_trace", {})
        self.assertIsInstance(trace, dict)
        self.assertTrue(str(trace.get("query_run_id", "")).startswith("qry_"))
        self.assertEqual(str(trace.get("method")), "classic")
        stage_ms = trace.get("stage_ms", {})
        self.assertIsInstance(stage_ms, dict)
        self.assertGreaterEqual(float(stage_ms.get("classic_query", 0.0)), 0.0)
        self.assertGreaterEqual(float(stage_ms.get("display", 0.0)), 0.0)
        self.assertGreater(float(stage_ms.get("total", 0.0)), 0.0)
        handoffs = trace.get("handoffs", [])
        self.assertIsInstance(handoffs, list)
        self.assertGreaterEqual(len(handoffs), 2)
        rel_paths = [str(call.kwargs.get("rel_path", "")) for call in append_mock.call_args_list]
        self.assertIn("query_eval.ndjson", rel_paths)
        self.assertIn("query_trace.ndjson", rel_paths)


if __name__ == "__main__":
    unittest.main()
