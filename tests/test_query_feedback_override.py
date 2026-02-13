import json
import tempfile
import unittest
from pathlib import Path

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


class QueryFeedbackOverrideTests(unittest.TestCase):
    def test_query_does_not_override_answer_from_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            facts = Path(tmp) / "facts"
            facts.mkdir(parents=True, exist_ok=True)
            feedback = {
                "schema_version": 2,
                "record_type": "derived.eval.feedback",
                "ts_utc": "2026-02-11T00:00:00Z",
                "query_run_id": "qry_old",
                "query": "what are the two tabs",
                "verdict": "disagree",
                "score_bp": 0,
                "expected_answer": "logviewer and bg_member",
                "actual_answer": "wrong",
            }
            (facts / "query_feedback.ndjson").write_text(json.dumps(feedback) + "\n", encoding="utf-8")

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
                        "text": "unrelated text",
                        "span_ref": {"kind": "text", "note": "test"},
                        "content_hash": "hash_d",
                    },
                }
            )
            system = _System(
                config={
                    "runtime": {"run_id": "run_test"},
                    "storage": {"data_dir": str(tmp)},
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
            out = run_query(system, "what are the two tabs")
            summary = (((out.get("answer") or {}).get("display") or {}).get("summary") or "").strip()
            self.assertNotEqual(summary, "logviewer and bg_member")
            processing = out.get("processing", {})
            self.assertTrue(isinstance(processing, dict))
            self.assertFalse(isinstance(processing.get("feedback_override"), dict))

    def test_query_rejects_derived_eval_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_id = "run_test/evidence.capture.segment/seg1"
            disallowed_id = "run_test/derived.eval.feedback/fb1"
            metadata = _Meta(
                {
                    evidence_id: {
                        "record_type": "evidence.capture.segment",
                        "content_hash": "hash_e",
                        "ts_utc": "2026-02-07T00:00:00Z",
                    },
                    disallowed_id: {
                        "record_type": "derived.eval.feedback",
                        "text": "expected answer text from evaluator",
                        "span_ref": {"kind": "text", "note": "test"},
                        "content_hash": "hash_d",
                    },
                }
            )
            system = _System(
                config={
                    "runtime": {"run_id": "run_test"},
                    "storage": {"data_dir": str(tmp)},
                    "processing": {"state_layer": {"query_enabled": False}, "on_query": {"allow_decode_extract": False}},
                    "plugins": {"locks": {"lockfile": "config/plugin_locks.json"}},
                },
                caps={
                    "time.intent_parser": _Parser(),
                    "retrieval.strategy": _Retrieval([{"record_id": evidence_id, "derived_id": disallowed_id, "ts_utc": "2026-02-07T00:00:00Z"}]),
                    "answer.builder": _Answer(),
                    "storage.metadata": metadata,
                    "event.builder": _EventBuilder(),
                },
            )
            out = run_query(system, "what are the two tabs")
            answer = out.get("answer", {})
            claims = answer.get("claims", []) if isinstance(answer, dict) else []
            self.assertEqual(claims, [])
            self.assertEqual(str(answer.get("state") or ""), "no_evidence")
            policy = out.get("processing", {}).get("policy", {})
            self.assertEqual(int(policy.get("source_rejections_count", 0) or 0), 1)


if __name__ == "__main__":
    unittest.main()
