import unittest

from autocapture.indexing.vector import qdrant_healthcheck


class QdrantHealthcheckTests(unittest.TestCase):
    def test_healthcheck_skipped_by_default(self) -> None:
        result = qdrant_healthcheck()
        self.assertIn("ok", result)
        self.assertTrue(result.get("skipped", False))


if __name__ == "__main__":
    unittest.main()
