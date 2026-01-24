import tempfile
import unittest
from pathlib import Path

from tools.validate_blueprint_spec import validate_spec


class BlueprintSpecValidationTests(unittest.TestCase):
    def test_spec_passes(self):
        project_root = Path(__file__).resolve().parents[1]
        spec_path = project_root / "docs" / "spec" / "autocapture_nx_blueprint_2026-01-24.md"
        result = validate_spec(spec_path, project_root)
        self.assertTrue(result.ok, msg=f"Spec errors: {result.errors}")

    def test_missing_sections_fails(self):
        project_root = Path(__file__).resolve().parents[1]
        content = "Source_Document: docs/spec/autocapture_nx_blueprint_2026-01-24.md\n\n# 1. Source_Index\n"
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.md"
            spec_path.write_text(content, encoding="utf-8")
            result = validate_spec(spec_path, project_root)
            self.assertFalse(result.ok)
            self.assertIn("sections_mismatch", result.errors)


if __name__ == "__main__":
    unittest.main()
