import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex, LocalEmbedder
from autocapture.retrieval.rerank import Reranker
from autocapture.retrieval.tiers import TieredRetriever


class TierPlannerEscalationTests(unittest.TestCase):
    def test_escalates_to_fusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lexical = LexicalIndex(Path(tmp) / "lexical.db")
            vector = VectorIndex(Path(tmp) / "vector.db", LocalEmbedder(None))
            vector.index("doc1", "hello world")
            retriever = TieredRetriever(lexical, vector, Reranker(), fast_threshold=2, fusion_threshold=1)
            result = retriever.retrieve("hello")
            tiers = [t["tier"] for t in result["trace"]]
            self.assertIn("FUSION", tiers)

    def test_escalates_to_rerank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lexical = LexicalIndex(Path(tmp) / "lexical.db")
            vector = VectorIndex(Path(tmp) / "vector.db", LocalEmbedder(None))
            vector.index("doc1", "hello world")
            retriever = TieredRetriever(lexical, vector, Reranker(), fast_threshold=5, fusion_threshold=5)
            result = retriever.retrieve("hello")
            tiers = [t["tier"] for t in result["trace"]]
            self.assertIn("RERANK", tiers)


if __name__ == "__main__":
    unittest.main()
