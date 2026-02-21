import unittest

from autocapture.indexing.vector import LocalEmbedder


class EmbedderDeterminismTests(unittest.TestCase):
    def test_embedding_is_deterministic(self) -> None:
        embedder = LocalEmbedder(None)
        vec1 = embedder.embed("Deterministic test")
        vec2 = embedder.embed("Deterministic test")
        self.assertEqual(vec1, vec2)
        self.assertEqual(len(vec1), 384)


if __name__ == "__main__":
    unittest.main()
