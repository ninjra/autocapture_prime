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
            export_path = Path(tmp) / "vector.json"
            payload = index.export_json(export_path)
            self.assertEqual(payload.get("doc_ids"), ["doc1"])
            reloaded = VectorIndex(Path(tmp) / "vector2.db", LocalEmbedder(None))
            reloaded.import_json(export_path)
            hits = reloaded.query("hello")
            self.assertTrue(any(hit.doc_id == "doc1" for hit in hits))


if __name__ == "__main__":
    unittest.main()
