import json
import tempfile
import unittest
from pathlib import Path

from autocapture.config.load import load_config
from autocapture.config.models import ConfigPaths
from autocapture.ux.preview_tokens import preview_tokens


class SettingsPreviewTokensTests(unittest.TestCase):
    def test_preview_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ConfigPaths(
                default_path=Path("config/default.json"),
                user_path=Path(tmp) / "user.json",
                schema_path=Path("contracts/config_schema.json"),
                backup_dir=Path(tmp) / "backup",
            )
            override = {
                "storage": {
                    "data_dir": tmp,
                    "crypto": {
                        "keyring_path": f"{tmp}/keyring.json",
                        "root_key_path": f"{tmp}/root.key",
                    },
                }
            }
            paths.user_path.write_text(json.dumps(override), encoding="utf-8")
            config = load_config(paths, safe_mode=False)
            result = preview_tokens("john@example.com", config)
            self.assertIn("tokens", result)
            self.assertNotIn("john@example.com", result["text"])


if __name__ == "__main__":
    unittest.main()
