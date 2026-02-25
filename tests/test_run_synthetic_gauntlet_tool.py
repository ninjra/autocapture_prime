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
    def test_default_case_paths_include_temporal_suite(self) -> None:
        mod = _load_module()
        paths = list(getattr(mod, "DEFAULT_CASE_PATHS", []))
        self.assertIn("docs/query_eval_cases_temporal_screenshot_qa_40.json", paths)

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

    def test_evaluate_case_memory_style_strict_tokens_pass(self) -> None:
        mod = _load_module()
        case = {
            "id": "mem1",
            "query": "How many characters were typed in the latest window?",
            "expects_all": ["characters", "latest window"],
            "require_citations": True,
        }
        result = {
            "answer": {
                "display": {"summary": "Latest window characters typed: 182"},
                "claims": [{"text": "Latest window characters typed: 182", "citations": [{"evidence_id": "e1"}]}],
            }
        }
        strict_case, passed, detail = mod._evaluate_case(case, result)  # noqa: SLF001
        self.assertTrue(strict_case)
        self.assertTrue(passed)
        self.assertEqual(detail, "ok")

    def test_evaluate_case_memory_style_strict_fails_without_citations(self) -> None:
        mod = _load_module()
        case = {
            "id": "mem2",
            "query": "How many characters were typed in the latest window?",
            "expects_any": ["characters typed"],
            "require_citations": True,
        }
        result = {
            "answer": {
                "display": {"summary": "characters typed: 54"},
                "claims": [{"text": "characters typed: 54", "citations": []}],
            }
        }
        strict_case, passed, detail = mod._evaluate_case(case, result)  # noqa: SLF001
        self.assertTrue(strict_case)
        self.assertFalse(passed)
        self.assertIn("citations_ok=False", detail)


if __name__ == "__main__":
    unittest.main()
