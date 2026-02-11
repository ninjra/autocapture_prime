from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/query_eval_suite.py")
    spec = importlib.util.spec_from_file_location("query_eval_suite_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class QueryEvalSuiteExactTests(unittest.TestCase):
    def test_run_case_supports_exact_expectation(self) -> None:
        mod = _load_module()
        case = {
            "id": "inboxes",
            "query": "how many inboxes do i have open",
            "expect_exact": "Open inboxes: 4",
            "require_citations": True,
        }
        result = {
            "answer": {
                "claims": [{"text": "Open inboxes: 4", "citations": [{"evidence_id": "e1"}]}],
                "state": "ok",
                "errors": [],
            }
        }
        with mock.patch.object(mod, "run_query", return_value=result):
            out = mod._run_case(object(), case)
        self.assertTrue(out.passed)

    def test_run_case_fails_without_citations_when_required(self) -> None:
        mod = _load_module()
        case = {
            "id": "time",
            "query": "what time is it on the vdi",
            "expect_exact": "VDI time: 11:35 AM",
            "require_citations": True,
        }
        result = {
            "answer": {
                "claims": [{"text": "VDI time: 11:35 AM", "citations": []}],
                "state": "ok",
                "errors": [],
            }
        }
        with mock.patch.object(mod, "run_query", return_value=result):
            out = mod._run_case(object(), case)
        self.assertFalse(out.passed)
        self.assertIn("citations_ok=False", out.detail)


if __name__ == "__main__":
    unittest.main()
