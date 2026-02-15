from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autocapture_prime.store.index import build_lexical_index, search_lexical_index


class ChronicleIndexDeterminismTests(unittest.TestCase):
    def test_search_order_is_stable(self) -> None:
        rows = [
            {"text": "inbox task", "frame_index": 1, "extractor": "ocr.basic"},
            {"text": "task inbox", "frame_index": 2, "extractor": "ocr.basic"},
            {"text": "calendar", "frame_index": 3, "extractor": "ocr.basic"},
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lexical_index.json"
            build_lexical_index(rows, path)
            out1 = search_lexical_index(path, rows, "inbox task", top_k=2)
            out2 = search_lexical_index(path, rows, "inbox task", top_k=2)
        self.assertEqual(out1, out2)
        self.assertEqual(len(out1), 2)
        self.assertIn("_score", out1[0])
        self.assertIn("_rank", out1[0])
        self.assertIn("_row_idx", out1[0])
        self.assertGreaterEqual(int(out1[0]["_score"]), int(out1[1]["_score"]))


if __name__ == "__main__":
    unittest.main()
