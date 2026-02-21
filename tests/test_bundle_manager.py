import unittest
from pathlib import Path

from autocapture.models.bundles import discover_bundles, select_bundle


class BundleManagerTests(unittest.TestCase):
    def test_select_bundle_prefers_latest_version(self) -> None:
        root = Path("tests/fixtures/bundles")
        bundles = discover_bundles([root])
        self.assertTrue(bundles)
        selected = select_bundle("ner", [root])
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.bundle_id, "ner.alpha")
        self.assertEqual(selected.version, "2.0.0")


if __name__ == "__main__":
    unittest.main()
