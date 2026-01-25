import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.vector import VectorIndex, LocalEmbedder


class VectorIndexRoundtripTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = VectorIndex(Path(tmp) / "vector.db", LocalEmbedder(None))
            index.index("doc1", "hello world")
            hits = index.query("hello")
            self.assertTrue(any(hit.doc_id == "doc1" for hit in hits))


if __name__ == "__main__":
    unittest.main()
