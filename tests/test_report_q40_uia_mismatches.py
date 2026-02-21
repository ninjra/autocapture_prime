from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_module():
    path = Path("tools/report_q40_uia_mismatches.py")
    spec = importlib.util.spec_from_file_location("report_q40_uia_mismatches_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(
    *,
    case_id: str,
    checks: list[dict],
    providers: list[dict],
    skipped: bool = False,
    ok: bool = True,
    passed: bool = False,
) -> dict:
    return {
        "id": case_id,
        "question": f"Question {case_id}",
        "summary": f"Summary {case_id}",
        "ok": ok,
        "skipped": skipped,
        "providers": providers,
        "expected_eval": {"passed": passed, "checks": checks},
    }


class ReportQ40UIAMismatchesTests(unittest.TestCase):
    def test_generate_report_classifies_expected_categories(self) -> None:
        mod = _load_module()
        advanced = {
            "rows": [
                _row(
                    case_id="Q1",
                    checks=[{"type": "expected_answer", "mode": "structured_exact", "match": False}],
                    providers=[{"provider_id": "builtin.observation.graph", "citation_count": 2, "contribution_bp": 9000}],
                ),
                _row(
                    case_id="Q2",
                    checks=[{"type": "contains_all", "present": False}],
                    providers=[{"provider_id": "builtin.observation.graph", "citation_count": 0, "contribution_bp": 0}],
                ),
            ]
        }
        generic = {
            "rows": [
                _row(
                    case_id="GQ1",
                    checks=[{"type": "pipeline_enforcement", "key": "disallowed_answer_provider_activity", "present": False}],
                    providers=[{"provider_id": "hard_vlm.direct", "citation_count": 1, "contribution_bp": 1000}],
                ),
                _row(
                    case_id="GQ2",
                    checks=[{"type": "contains_all", "present": False}],
                    providers=[{"provider_id": "builtin.observation.graph", "citation_count": 1, "contribution_bp": 6000}],
                ),
            ]
        }
        report = mod.generate_report(advanced, generic, matrix=None)
        counts = report["category_counts"]
        self.assertEqual(int(report["total_failures"]), 4)
        self.assertEqual(int(counts.get("exact_answer_mismatch", 0)), 1)
        self.assertEqual(int(counts.get("missing_evidence", 0)), 1)
        self.assertEqual(int(counts.get("provider_path_inconsistency", 0)), 1)
        self.assertEqual(int(counts.get("evidence_present_but_nonmatching", 0)), 1)

    def test_markdown_contains_table_rows(self) -> None:
        mod = _load_module()
        payload = {
            "generated_utc": "2026-02-19T00:00:00Z",
            "total_failures": 1,
            "category_counts": {"missing_evidence": 1},
            "rows": [
                {
                    "suite": "advanced20",
                    "id": "Q9",
                    "category": "missing_evidence",
                    "reason": "no_positive_evidence_trace",
                    "citation_total": 0,
                    "provider_ids": [],
                }
            ],
        }
        md = mod._to_markdown(payload)
        self.assertIn("| suite | id | category | reason | citation_total | providers |", md)
        self.assertIn("| advanced20 | Q9 | missing_evidence | no_positive_evidence_trace | 0 |  |", md)


if __name__ == "__main__":
    unittest.main()
