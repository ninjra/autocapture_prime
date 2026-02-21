import unittest
import os
import tempfile

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class QueryTests(unittest.TestCase):
    def test_query_returns_answer(self):
        try:
            import sqlcipher3  # noqa: F401
        except Exception:
            self.skipTest("sqlcipher3 not available")
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                kernel = Kernel(default_config_paths(), safe_mode=True)
                system = kernel.boot()
                try:
                    result = __import__("autocapture_nx.kernel.query", fromlist=["run_query"]).run_query(system, "test")
                    self.assertIn("answer", result)
                finally:
                    kernel.shutdown()
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
