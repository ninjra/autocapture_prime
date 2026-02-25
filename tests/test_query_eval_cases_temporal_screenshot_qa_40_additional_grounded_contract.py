from __future__ import annotations

import json
import unittest
from pathlib import Path


class TemporalQa40AdditionalGroundedCaseContractTests(unittest.TestCase):
    def test_case_file_has_40_rows_unique_ids_and_expected_paths(self) -> None:
        path = Path("docs/query_eval_cases_temporal_screenshot_qa_40_additional_grounded.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 40)

        ids: list[str] = []
        for row in payload:
            self.assertIsInstance(row, dict)
            case_id = str(row.get("id") or "").strip()
            self.assertTrue(case_id)
            ids.append(case_id)
            self.assertTrue(str(row.get("question") or "").strip())
            self.assertTrue(bool(row.get("expected_paths")))
        self.assertEqual(len(set(ids)), 40)


if __name__ == "__main__":
    unittest.main()
