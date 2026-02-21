import unittest

from tools import frozen_surfaces


class FrozenSurfaceTests(unittest.TestCase):
    def test_frozen_surfaces_gate(self) -> None:
        current = frozen_surfaces.compute_surfaces()
        baseline = frozen_surfaces._load_baseline()
        report = frozen_surfaces.compare_surfaces(baseline, current)
        self.assertTrue(report.get("schema_ok"), f"schema mismatches: {report.get('schema_mismatches')}")
        self.assertTrue(report.get("ok"), f"frozen surface churn: {report.get('changes')}")


if __name__ == "__main__":
    unittest.main()
