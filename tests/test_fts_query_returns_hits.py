import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex


class FtsQueryTests(unittest.TestCase):
    def test_fts_query_returns_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = LexicalIndex(Path(tmp) / "lexical.db")
            index.index("doc1", "hello world")
            hits = index.query("hello")
            self.assertTrue(any(hit["doc_id"] == "doc1" for hit in hits))


if __name__ == "__main__":
    unittest.main()
