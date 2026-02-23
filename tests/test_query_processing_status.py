import os
import tempfile
import unittest

from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.query import run_query


class QueryProcessingStatusTests(unittest.TestCase):
    def test_query_processing_blocked_metadata(self) -> None:
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
                system = kernel.boot(start_conductor=False)
                try:
                    result = run_query(system, "test query")
                    processing = result.get("processing", {})
                    extraction = processing.get("extraction", {})
                    self.assertIsInstance(extraction, dict)
                    self.assertIn("allowed", extraction)
                    self.assertIn("ran", extraction)
                    self.assertIn("blocked", extraction)
                    self.assertEqual(extraction.get("allowed"), False)
                    self.assertEqual(extraction.get("blocked_reason"), "query_compute_disabled")
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
