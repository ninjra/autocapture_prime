import json
import tempfile
import unittest
from pathlib import Path

from autocapture.memory.entities import build_hasher
from autocapture.config.load import load_config
from autocapture.config.models import ConfigPaths


class EntityHashingStableTests(unittest.TestCase):
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

    def test_deterministic_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            hasher, entity_map = build_hasher(config)
            text = "Email john@example.com and call 555-123-4567."
            first, tokens1 = hasher.sanitize_text(text, "default", entity_map, config)
            second, tokens2 = hasher.sanitize_text(text, "default", entity_map, config)
            self.assertEqual(tokens1, tokens2)
            self.assertEqual(first, second)

    def test_different_values_change_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            hasher, entity_map = build_hasher(config)
            first, tokens1 = hasher.sanitize_text("john@example.com", "default", entity_map, config)
            second, tokens2 = hasher.sanitize_text("jane@example.com", "default", entity_map, config)
            self.assertNotEqual(tokens1, tokens2)
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
