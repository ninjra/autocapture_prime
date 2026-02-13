from __future__ import annotations

import json
import os
import tempfile
import unittest

from autocapture_nx.kernel.query import _append_query_metric


class _DummySystem:
    def __init__(self, data_dir: str) -> None:
        self.config = {"storage": {"data_dir": data_dir}}


class QueryEvalMetricsAppendTests(unittest.TestCase):
    def test_append_query_metric_writes_fact_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            system = _DummySystem(tmp)
            result = {
                "answer": {"state": "ok", "claims": [{"text": "x", "citations": []}]},
                "results": [{"record_id": "r1"}],
                "evaluation": {"coverage_ratio": 1.0, "missing_spans_count": 0, "blocked_extract": False},
                "custom_claims": {"count": 1},
                "synth_claims": {"count": 1, "debug": {"backend": "openai_compat", "model": "m"}},
                "provenance": {"query_ledger_head": "h", "anchor_ref": "a"},
                "processing": {"extraction": {"extracted_count": 0, "candidate_count": 1}},
            }
            _append_query_metric(system, query="what song is playing", method="classic", result=result)
            path = os.path.join(tmp, "facts", "query_eval.ndjson")
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload.get("record_type"), "derived.query.eval")
            self.assertEqual(payload.get("method"), "classic")
            self.assertEqual(payload.get("answer_state"), "ok")


if __name__ == "__main__":
    unittest.main()

