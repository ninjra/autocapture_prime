import unittest
from pathlib import Path


class UISmokeTests(unittest.TestCase):
    def test_ui_assets_exist_and_index_links(self) -> None:
        root = Path("autocapture/web/ui")
        index = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn("app.js", index)
        self.assertIn("styles.css", index)
        self.assertTrue((root / "app.js").exists())
        self.assertTrue((root / "styles.css").exists())


if __name__ == "__main__":
    unittest.main()

