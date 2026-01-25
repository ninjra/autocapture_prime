import json
import tempfile
import unittest
from pathlib import Path

from autocapture.config.load import load_config
from autocapture.config.models import ConfigPaths
from autocapture.ux.redaction import EgressSanitizer


class SanitizerNoRawPIITests(unittest.TestCase):
    def _config(self, tmp: str) -> dict:
        paths = ConfigPaths(
            default_path=Path("config/default.json"),
            user_path=Path(tmp) / "user.json",
            schema_path=Path("contracts/config_schema.json"),
            backup_dir=Path(tmp) / "backup",
        )
        override = {
            "storage": {
                "data_dir": tmp.replace("\\", "/"),
                "crypto": {
                    "keyring_path": f"{tmp}/keyring.json",
                    "root_key_path": f"{tmp}/root.key",
                },
            }
        }
        paths.user_path.write_text(json.dumps(override), encoding="utf-8")
        return load_config(paths, safe_mode=False)

    def test_sanitizer_removes_pii(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            sanitizer = EgressSanitizer(config)
            payload = {"text": "Contact John Doe at john@example.com"}
            sanitized = sanitizer.sanitize_payload(payload)
            self.assertNotIn("john@example.com", sanitized["text"])
            self.assertTrue(sanitizer.leak_check(sanitized))


if __name__ == "__main__":
    unittest.main()
