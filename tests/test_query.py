import unittest

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class QueryTests(unittest.TestCase):
    def test_query_returns_answer(self):
        try:
            import sqlcipher3  # noqa: F401
        except Exception:
            self.skipTest("sqlcipher3 not available")
        kernel = Kernel(default_config_paths(), safe_mode=True)
        system = kernel.boot()
        result = __import__("autocapture_nx.kernel.query", fromlist=["run_query"]).run_query(system, "test")
        self.assertIn("answer", result)


if __name__ == "__main__":
    unittest.main()
