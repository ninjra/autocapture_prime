import unittest

from autocapture.retrieval.rerank import Reranker


class RerankerDeterminismTests(unittest.TestCase):
    def test_tie_breaks_by_doc_id(self) -> None:
        reranker = Reranker()
        docs = [
            {"doc_id": "b", "text": "alpha beta", "score": 0.0},
            {"doc_id": "a", "text": "alpha beta", "score": 0.0},
        ]
        ranked = reranker.rerank("alpha", docs)
        self.assertEqual([d["doc_id"] for d in ranked], ["a", "b"])

    def test_phrase_bonus_deterministic(self) -> None:
        reranker = Reranker()
        docs = [
            {"doc_id": "a", "text": "alpha beta gamma", "score": 0.0},
            {"doc_id": "b", "text": "alpha beta", "score": 0.0},
        ]
        ranked = reranker.rerank("alpha beta", docs)
        self.assertEqual(ranked[0]["doc_id"], "b")


if __name__ == "__main__":
    unittest.main()
