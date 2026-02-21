import os
import tempfile
import unittest

from autocapture.ux.facade import create_facade
from autocapture.ux.settings_schema import get_schema


class UXFacadeParityTests(unittest.TestCase):
    def test_settings_schema_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                facade = create_facade()
                schema = facade.settings_schema()
                legacy = get_schema()
                if "fields" in schema:
                    self.assertIn("schema_version", schema)
                    self.assertEqual(schema.get("schema_version"), legacy.get("schema_version"))
                else:
                    self.assertEqual(schema, legacy)
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
