from __future__ import annotations

import json
import unittest
from pathlib import Path


class TemporalScreenshotQa40CaseContractTests(unittest.TestCase):
    def test_temporal_qa40_has_full_case_count_and_unique_ids(self) -> None:
        path = Path("docs/query_eval_cases_temporal_screenshot_qa_40.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, list)
        cases = [row for row in payload if isinstance(row, dict)]
        self.assertEqual(len(cases), 40)
        ids = [str(row.get("id") or "").strip() for row in cases]
        self.assertEqual(len(ids), len([x for x in ids if x]))
        self.assertEqual(len(ids), len(set(ids)))

    def test_temporal_qa40_has_required_query_paths_and_modalities(self) -> None:
        path = Path("docs/query_eval_cases_temporal_screenshot_qa_40.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases = [row for row in payload if isinstance(row, dict)]
        modality_counts = {"uia": 0, "hid": 0, "ocr_text": 0, "vector": 0}
        for row in cases:
            expected_paths = row.get("expected_paths", [])
            self.assertIsInstance(expected_paths, list)
            self.assertGreaterEqual(len(expected_paths), 3)
            for spec in expected_paths:
                self.assertIsInstance(spec, dict)
                self.assertTrue(str(spec.get("path") or "").strip())
            modalities = row.get("modality_requirements", [])
            self.assertIsInstance(modalities, list)
            for key in modality_counts:
                if key in modalities:
                    modality_counts[key] += 1
        self.assertGreaterEqual(modality_counts["uia"], 20)
        self.assertGreaterEqual(modality_counts["hid"], 12)
        self.assertGreaterEqual(modality_counts["ocr_text"], 12)
        self.assertGreaterEqual(modality_counts["vector"], 1)


if __name__ == "__main__":
    unittest.main()

