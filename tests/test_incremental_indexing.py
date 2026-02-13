import tempfile
from pathlib import Path
import unittest

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.manifest import load_manifest
from autocapture.indexing.vector import VectorIndex, HashEmbedder


class IncrementalIndexingTests(unittest.TestCase):
    def test_indexes_skip_unchanged_documents(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lex_path = root / "lexical.db"
            vec_path = root / "vector.db"
            lexical = LexicalIndex(lex_path)
            vector = VectorIndex(vec_path, HashEmbedder(dims=32))
            doc_id = "run_test/derived.text.ocr/provider/seg1"
            text = "hello world"

            changed = lexical.index_if_changed(doc_id, text)
            self.assertTrue(changed)
            changed = vector.index_if_changed(doc_id, text)
            self.assertTrue(changed)
            lex_manifest_1 = load_manifest(lex_path, "lexical")
            vec_manifest_1 = load_manifest(vec_path, "vector")

            # Second pass should skip and not bump manifest versions.
            changed = lexical.index_if_changed(doc_id, text)
            self.assertFalse(changed)
            changed = vector.index_if_changed(doc_id, text)
            self.assertFalse(changed)
            lex_manifest_2 = load_manifest(lex_path, "lexical")
            vec_manifest_2 = load_manifest(vec_path, "vector")
            self.assertEqual(lex_manifest_1.version, lex_manifest_2.version)
            self.assertEqual(vec_manifest_1.version, vec_manifest_2.version)


if __name__ == "__main__":
    unittest.main()
