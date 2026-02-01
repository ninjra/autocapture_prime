import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex, LocalEmbedder
from autocapture.retrieval.rerank import Reranker
from autocapture.retrieval.tiers import TieredRetriever


class RetrievalGoldenTests(unittest.TestCase):
    def test_golden_corpus_recall_precision(self) -> None:
        # Rationale: On a tiny deterministic corpus, we expect at least one
        # relevant document in the top 3 (precision >= 0.34) and full recall
        # for single-target queries (recall == 1.0).
        corpus = {
            "doc.alpha": "alpha beta gamma",
            "doc.blue_apple": "blue apple orchard and harvest",
            "doc.apple": "red apple banana fruit",
            "doc.blue_sky": "blue sky cloud horizon",
        }
        queries = [
            ("blue apple", {"doc.blue_apple"}),
            ("red apple", {"doc.apple"}),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            lexical = LexicalIndex(Path(tmp) / "lexical.db")
            vector = VectorIndex(Path(tmp) / "vector.db", LocalEmbedder(None))
            for doc_id, text in corpus.items():
                lexical.index(doc_id, text)
                vector.index(doc_id, text)
            retriever = TieredRetriever(lexical, vector, Reranker(), fast_threshold=1, fusion_threshold=2, rrf_k=60)

            for query, expected in queries:
                result = retriever.retrieve(query)
                top = [item["doc_id"] for item in result["results"][:3]]
                hits = expected.intersection(top)
                precision = len(hits) / max(1, len(top))
                recall = len(hits) / max(1, len(expected))
                self.assertGreaterEqual(precision, 0.34)
                self.assertEqual(recall, 1.0)


if __name__ == "__main__":
    unittest.main()
