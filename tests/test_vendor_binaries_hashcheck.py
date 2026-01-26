import os
import unittest

from autocapture.tools.vendor_windows_binaries import verify_binaries


class VendorBinariesHashcheckTests(unittest.TestCase):
    def test_vendor_binaries(self) -> None:
        report = verify_binaries()
        self.assertIn("ok", report)
        if os.name != "nt":
            self.assertTrue(report["ok"])
            self.assertTrue(report.get("skipped", False))


if __name__ == "__main__":
    unittest.main()
