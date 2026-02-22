from __future__ import annotations

import json
import unittest
from pathlib import Path


class Stage2Time40CaseContractTests(unittest.TestCase):
    def test_stage2_time40_has_full_case_count_and_unique_ids(self) -> None:
        path = Path("docs/query_eval_cases_stage2_time40.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, list)
        cases = [row for row in payload if isinstance(row, dict)]
        self.assertGreaterEqual(len(cases), 40)
        ids = [str(row.get("id") or "").strip() for row in cases]
        self.assertEqual(len(ids), len([x for x in ids if x]))
        self.assertEqual(len(ids), len(set(ids)))

    def test_stage2_time40_covers_memory_time_and_typing_prompts(self) -> None:
        path = Path("docs/query_eval_cases_stage2_time40.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases = [row for row in payload if isinstance(row, dict)]
        questions = [str(row.get("question") or "").lower() for row in cases]
        typing_questions = [q for q in questions if "characters" in q or "typed" in q]
        window_questions = [q for q in questions if "window" in q or "contiguous" in q]
        self.assertGreaterEqual(len(typing_questions), 8)
        self.assertGreaterEqual(len(window_questions), 8)
        for row in cases:
            expected_paths = row.get("expected_paths", [])
            self.assertIsInstance(expected_paths, list)
            self.assertGreaterEqual(len(expected_paths), 3)


if __name__ == "__main__":
    unittest.main()
