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

    def test_rrf_handles_mixed_doc_id_types(self) -> None:
        rankings = [
            [{"doc_id": 10}, {"doc_id": "2"}],
            [{"record_id": "10"}, {"record_id": 2}],
        ]
        out = rrf_fusion(rankings)
        self.assertTrue(out)
        # All normalized to strings; no mixed-type sort exceptions.
        self.assertTrue(all(isinstance(row.get("doc_id"), str) for row in out))


if __name__ == "__main__":
    unittest.main()
