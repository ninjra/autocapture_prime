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

    def test_fts_query_handles_punctuation_and_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = LexicalIndex(Path(tmp) / "lexical.db")
            index.index("doc1", "How many inboxes do I have open? Open inboxes: 1")
            hits = index.query("How many inboxes do I have open?")
            self.assertTrue(any(hit["doc_id"] == "doc1" for hit in hits))


if __name__ == "__main__":
    unittest.main()
