import unittest
from pathlib import Path


class DocsConsistencySmokeTests(unittest.TestCase):
    def test_core_runtime_statement_present(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        surface = Path("contracts/user_surface.md").read_text(encoding="utf-8")
        self.assertIn("autocapture_nx", readme)
        self.assertIn("Core runtime", surface)
        self.assertIn("autocapture_nx", surface)


if __name__ == "__main__":
    unittest.main()

