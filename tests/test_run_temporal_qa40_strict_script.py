from __future__ import annotations

import unittest
from pathlib import Path


class RunTemporalQa40StrictScriptTests(unittest.TestCase):
    def test_script_references_temporal_cases_and_strict_counts(self) -> None:
        path = Path("tools/run_temporal_qa40_strict.sh")
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("docs/query_eval_cases_temporal_screenshot_qa_40.json", text)
        self.assertIn("--expected-evaluated 40", text)
        self.assertIn("--expected-skipped 0", text)
        self.assertIn("--expected-failed 0", text)
        self.assertIn("tools/gate_temporal40_semantic.py", text)
        self.assertIn("--expected-passed 40", text)
        self.assertIn("temporal40_semantic_gate_latest.json", text)


if __name__ == "__main__":
    unittest.main()
