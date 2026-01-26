import unittest

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths


class CaptureBackendDefaultTests(unittest.TestCase):
    def test_default_backend_is_supported(self) -> None:
        config = load_config(default_config_paths(), safe_mode=False)
        backend = config.get("capture", {}).get("video", {}).get("backend")
        self.assertEqual(backend, "mss")


if __name__ == "__main__":
    unittest.main()
