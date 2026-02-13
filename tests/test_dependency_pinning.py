import os
import tempfile
import unittest
from unittest import mock

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class DependencyPinningTests(unittest.TestCase):
    def test_doctor_detects_dependency_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            kernel = Kernel(default_config_paths(), safe_mode=False)
            kernel.boot(start_conductor=False)
            try:
                # Force a deterministic mismatch regardless of the host environment.
                with mock.patch.object(kernel, "_package_versions", return_value={}):
                    checks = kernel.doctor()
                by_name = {c.name: c for c in checks}
                self.assertIn("dependency_pinning", by_name)
                self.assertFalse(by_name["dependency_pinning"].ok)
                self.assertIn("missing:", by_name["dependency_pinning"].detail or "")
            finally:
                kernel.shutdown()
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

