from __future__ import annotations

import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class _Parser:
    def parse(self, _query: str) -> dict:
        return {"time_window": None}


class _Retrieval:
    def search(self, _query: str, time_window=None):
        _ = time_window
        return [{"record_id": "run1/segment/0", "score": 1, "ts_utc": "2026-01-01T00:00:00+00:00"}]

    def trace(self):
        return []


class _Answer:
    def build(self, claims):
        return {"state": "ok", "claims": claims, "errors": []}


class _Metadata:
    def get(self, _key: str, default=None):
        return {"text": "hello world", "record_type": "evidence.capture.segment", "content_hash": "h1"}

    def keys(self):
        return ["run1/segment/0"]


class _EventBuilder:
    run_id = "run1"

    def ledger_entry(self, *_args, **_kwargs):
        return "hash"

    def last_anchor(self):
        return "anchor"


class _System:
    def __init__(self, *, require_query_path: bool) -> None:
        self.config = {
            "runtime": {"run_id": "run1"},
            "processing": {"on_query": {"allow_decode_extract": False}},
            "plugins": {"locks": {"lockfile": "config/plugin_locks.json"}},
            "promptops": {
                "enabled": True,
                "require_query_path": bool(require_query_path),
                "query_strategy": "normalize_query",
                "model_strategy": "model_contract",
                "require_citations": True,
                "persist_query_prompts": True,
                "history": {"enabled": False},
                "github": {"enabled": False},
                "sources": [],
                "examples": {},
                "metrics": {"enabled": False},
                "review": {"enabled": False},
            },
        }
        self._caps = {
            "time.intent_parser": _Parser(),
            "retrieval.strategy": _Retrieval(),
            "answer.builder": _Answer(),
            "storage.metadata": _Metadata(),
            "event.builder": _EventBuilder(),
        }

    def get(self, name: str):
        return self._caps[name]


class PromptOpsRequiredPathTests(unittest.TestCase):
    def test_required_promptops_path_fails_closed_when_layer_unavailable(self) -> None:
        system = _System(require_query_path=True)
        with mock.patch.object(query_mod, "_get_promptops_api", return_value=None):
            out = query_mod.run_query(system, "hello")
        answer = out.get("answer", {}) if isinstance(out.get("answer"), dict) else {}
        processing = out.get("processing", {}) if isinstance(out.get("processing"), dict) else {}
        promptops = processing.get("promptops", {}) if isinstance(processing.get("promptops"), dict) else {}
        trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace"), dict) else {}

        self.assertEqual(str(answer.get("state") or ""), "indeterminate")
        self.assertTrue(bool(promptops.get("required_failed", False)))
        self.assertEqual(str((answer.get("errors") or [{}])[0].get("error") or ""), "promptops_required_unavailable")
        self.assertTrue(bool(trace.get("promptops_required", False)))
        self.assertTrue(bool(trace.get("promptops_required_failed", False)))

    def test_non_required_promptops_path_does_not_fail_closed(self) -> None:
        system = _System(require_query_path=False)
        with mock.patch.object(query_mod, "_get_promptops_api", return_value=None):
            out = query_mod.run_query(system, "hello")
        answer = out.get("answer", {}) if isinstance(out.get("answer"), dict) else {}
        processing = out.get("processing", {}) if isinstance(out.get("processing"), dict) else {}
        promptops = processing.get("promptops", {}) if isinstance(processing.get("promptops"), dict) else {}

        self.assertNotEqual(str(answer.get("state") or ""), "indeterminate")
        self.assertFalse(bool(promptops.get("required_failed", False)))


if __name__ == "__main__":
    unittest.main()
