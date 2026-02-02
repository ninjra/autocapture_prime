import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from autocapture.web.api import get_app


class SettingsSchemaEndpointTests(unittest.TestCase):
    def test_settings_schema_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = get_app()
            try:
                client = TestClient(app)
                resp = client.get("/api/settings/schema")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("defaults", data)
                self.assertIn("current", data)
                self.assertIn("groupings", data)
                self.assertIn("descriptions", data)
                self.assertIn("fields", data)
                groupings = data.get("groupings", {}).get("fields", [])
                self.assertIsInstance(groupings, list)
                field_paths = {f.get("path") for f in data.get("fields", []) if isinstance(f, dict)}
                self.assertIn("capture.video.enabled", field_paths)
                entry = next((g for g in groupings if g.get("path") == "capture.video.enabled"), None)
                self.assertIsNotNone(entry)
                self.assertIn("ui_group", entry)
                self.assertIn("advanced", entry)
                self.assertIn("description", entry)
            finally:
                try:
                    app.state.facade.shutdown()
                except Exception:
                    pass
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
