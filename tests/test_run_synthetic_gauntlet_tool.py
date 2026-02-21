from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/run_synthetic_gauntlet.py")
    spec = importlib.util.spec_from_file_location("run_synthetic_gauntlet_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SyntheticGauntletToolTests(unittest.TestCase):
    def test_evaluate_case_strict_exact_passes(self) -> None:
        mod = _load_module()
        case = {"id": "c1", "query": "x", "expect_exact": "Open inboxes: 4", "require_citations": True}
        result = {"answer": {"claims": [{"text": "Open inboxes: 4", "citations": [{"evidence_id": "e1"}]}]}}
        strict_case, passed, detail = mod._evaluate_case(case, result)  # noqa: SLF001
        self.assertTrue(strict_case)
        self.assertTrue(passed)
        self.assertEqual(detail, "ok")

    def test_run_bundle_accepts_question_fallback(self) -> None:
        mod = _load_module()
        with mock.patch.object(
            mod,
            "run_query",
            return_value={
                "answer": {
                    "state": "ok",
                    "claims": [{"text": "Focused app: terminal", "citations": []}],
                    "display": {},
                }
            },
        ):
            rows, summary = mod._run_bundle(  # noqa: SLF001
                object(),
                bundle_name="bundle",
                cases=[{"id": "q1", "question": "what app is focused"}],
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "q1")
        self.assertEqual(rows[0]["query"], "what app is focused")
        self.assertFalse(bool(rows[0]["strict"]))
        self.assertEqual(int(summary.get("cases_total") or 0), 1)


if __name__ == "__main__":
    unittest.main()
