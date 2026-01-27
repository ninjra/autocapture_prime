import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex, LocalEmbedder


class IndexManifestTests(unittest.TestCase):
    def test_manifest_versions_increment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lexical_path = Path(tmp) / "lexical.db"
            vector_path = Path(tmp) / "vector.db"

            lexical = LexicalIndex(lexical_path)
            vector = VectorIndex(vector_path, LocalEmbedder(None))

            lex_id0 = lexical.identity()
            vec_id0 = vector.identity()
            self.assertEqual(lex_id0["version"], 0)
            self.assertEqual(vec_id0["version"], 0)

            lexical.index("doc1", "hello world")
            vector.index("doc1", "hello world")

            lex_id1 = lexical.identity()
            vec_id1 = vector.identity()
            self.assertEqual(lex_id1["version"], 1)
            self.assertEqual(vec_id1["version"], 1)
            self.assertIsNotNone(lex_id1.get("digest"))
            self.assertIsNotNone(vec_id1.get("digest"))
            self.assertTrue(Path(lex_id1["manifest_path"]).exists())
            self.assertTrue(Path(vec_id1["manifest_path"]).exists())


if __name__ == "__main__":
    unittest.main()
