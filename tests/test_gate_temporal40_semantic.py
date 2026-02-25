from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/gate_temporal40_semantic.py")
    spec = importlib.util.spec_from_file_location("gate_temporal40_semantic_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GateTemporal40SemanticTests(unittest.TestCase):
    def test_missing_rule_classes_is_empty_for_temporal_cases(self) -> None:
        mod = _load_module()
        cases = json.loads(pathlib.Path("docs/query_eval_cases_temporal_screenshot_qa_40.json").read_text(encoding="utf-8"))
        missing = mod.missing_rule_classes(cases)
        self.assertEqual(missing, [])

    def test_evaluate_row_passes_for_matching_unique_windows_surface(self) -> None:
        mod = _load_module()
        case = {
            "id": "TQ01",
            "difficulty_class": "unique_windows_rolling",
            "question": "In the last 24 hours, what unique top-level windows were visible with first_seen and last_seen?",
        }
        row = {
            "id": "TQ01",
            "answer_state": "ok",
            "summary": "Unique windows with first_seen and last_seen times.",
            "bullets": [
                "1. app=Slack window=DM first_seen=2026-02-24T18:01:02 last_seen=2026-02-24T18:10:02",
                "2. app=Outlook window=Task first_seen=2026-02-24T18:12:00 last_seen=2026-02-24T18:30:00",
            ],
            "providers": [{"provider_id": "builtin.observation.graph", "citation_count": 2}],
        }
        out = mod.evaluate_row(case, row)
        self.assertTrue(bool(out.get("ok", False)))

    def test_evaluate_row_fails_when_surface_is_unrelated(self) -> None:
        mod = _load_module()
        case = {
            "id": "TQ03",
            "difficulty_class": "error_toast_inventory",
            "question": "List each distinct error or dialog with first_seen, last_seen, and total_visible_duration.",
        }
        row = {
            "id": "TQ03",
            "answer_state": "ok",
            "summary": "Slack channels and podcast tiles found.",
            "bullets": ["tile: Conan O'Brien Needs A Friend", "tile: Slack DM list"],
            "providers": [{"provider_id": "builtin.observation.graph", "citation_count": 1}],
        }
        out = mod.evaluate_row(case, row)
        self.assertFalse(bool(out.get("ok", True)))
        reasons = set(out.get("reasons", []))
        self.assertIn("lexical_overlap_low", reasons)

    def test_evaluate_row_allows_degraded_temporal_no_evidence_when_aligned(self) -> None:
        mod = _load_module()
        case = {
            "id": "TQ01",
            "difficulty_class": "unique_windows_rolling",
            "question": "In the last 24 hours, what unique top-level windows were visible with first_seen and last_seen?",
        }
        row = {
            "id": "TQ01",
            "answer_state": "no_evidence",
            "summary": "Indeterminate: no temporal aggregate evidence is available yet for this query in the normalized corpus.",
            "bullets": [
                "required_source: temporal aggregate rows with explicit first_seen/last_seen semantics",
                "query_markers: last_24_hours, first_seen, last_seen, windows",
            ],
            "providers": [{"provider_id": "builtin.answer.synth_vllm_localhost", "citation_count": 0}],
        }
        out = mod.evaluate_row(case, row)
        self.assertTrue(bool(out.get("ok", False)))
        self.assertTrue(bool(out.get("degraded_state", False)))

    def test_evaluate_row_rejects_degraded_no_evidence_when_not_aligned(self) -> None:
        mod = _load_module()
        case = {
            "id": "TQ01",
            "difficulty_class": "unique_windows_rolling",
            "question": "In the last 24 hours, what unique top-level windows were visible with first_seen and last_seen?",
        }
        row = {
            "id": "TQ01",
            "answer_state": "no_evidence",
            "summary": "No data.",
            "bullets": ["fallback: unavailable"],
            "providers": [{"provider_id": "builtin.answer.synth_vllm_localhost", "citation_count": 0}],
        }
        out = mod.evaluate_row(case, row)
        self.assertFalse(bool(out.get("ok", True)))
        reasons = set(out.get("reasons", []))
        self.assertIn("degraded_marker_missing", reasons)

    def test_main_fails_when_any_case_semantic_mismatch(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cases = root / "cases.json"
            report = root / "report.json"
            out = root / "gate.json"
            cases.write_text(
                json.dumps(
                    [
                        {
                            "id": "TQ01",
                            "difficulty_class": "unique_windows_rolling",
                            "question": "Unique windows with first_seen and last_seen.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            report.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "id": "TQ01",
                                "answer_state": "ok",
                                "summary": "Only class counts available.",
                                "bullets": ["counts: teams=4"],
                                "providers": [{"provider_id": "builtin.observation.graph", "citation_count": 1}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--report", str(report), "--cases", str(cases), "--output", str(out), "--expected-passed", "1"])
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            self.assertEqual(int(payload.get("counts", {}).get("semantic_failed", -1)), 1)


if __name__ == "__main__":
    unittest.main()
