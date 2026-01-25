import unittest

from autocapture.retrieval.fusion import rrf_fusion


class RRFFusionDeterminismTests(unittest.TestCase):
    def test_rrf_deterministic(self) -> None:
        rankings = [
            [{"doc_id": "a"}, {"doc_id": "b"}],
            [{"doc_id": "b"}, {"doc_id": "a"}],
        ]
        first = rrf_fusion(rankings)
        second = rrf_fusion(rankings)
        self.assertEqual(first, second)
        # Tie-breaking should be deterministic by doc_id
        self.assertEqual(first[0]["doc_id"], "a")


if __name__ == "__main__":
    unittest.main()
