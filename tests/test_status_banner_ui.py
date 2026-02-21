import unittest
from pathlib import Path


class StatusBannerUiTests(unittest.TestCase):
    def test_status_banner_elements_present(self) -> None:
        html = Path("autocapture/web/ui/index.html").read_text(encoding="utf-8")
        self.assertIn('id="captureStatusBanner"', html)
        self.assertIn('id="captureBannerState"', html)
        self.assertIn('id="processingBannerState"', html)
        self.assertIn('id="captureBannerLast"', html)
        self.assertIn('id="captureBannerDisk"', html)

    def test_status_banner_renderer_hook(self) -> None:
        js = Path("autocapture/web/ui/app.js").read_text(encoding="utf-8")
        self.assertIn("renderStatusBanner", js)
        self.assertIn("captureBannerState", js)
        self.assertIn("processingBannerState", js)


if __name__ == "__main__":
    unittest.main()
