import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture_nx.kernel.config import ConfigPaths, load_config, reset_user_config, restore_user_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.default_path = root / "default.json"
        self.user_path = root / "user.json"
        self.schema_path = root / "schema.json"
        self.backup_dir = root / "backup"
        shutil.copy("config/default.json", self.default_path)
        shutil.copy("contracts/config_schema.json", self.schema_path)
        self.paths = ConfigPaths(
            default_path=self.default_path,
            user_path=self.user_path,
            schema_path=self.schema_path,
            backup_dir=self.backup_dir,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_merge_overrides(self):
        with open(self.user_path, "w", encoding="utf-8") as handle:
            json.dump({"privacy": {"cloud": {"enabled": True}}}, handle)
        config = load_config(self.paths, safe_mode=False)
        self.assertTrue(config["privacy"]["cloud"]["enabled"])

    def test_safe_mode_ignores_user(self):
        with open(self.user_path, "w", encoding="utf-8") as handle:
            json.dump({"privacy": {"cloud": {"enabled": True}}}, handle)
        config = load_config(self.paths, safe_mode=True)
        self.assertFalse(config["privacy"]["cloud"]["enabled"])
        self.assertTrue(config["plugins"]["safe_mode"])

    def test_reset_and_restore(self):
        with open(self.user_path, "w", encoding="utf-8") as handle:
            json.dump({"profile": "temp"}, handle)
        reset_user_config(self.paths)
        with open(self.user_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertNotEqual(data.get("profile"), "temp")
        restore_user_config(self.paths)
        with open(self.user_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data.get("profile"), "temp")

    def test_metadata_only_prefers_live_metadata_db_when_available(self):
        data_dir = Path(self.tempdir.name) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "metadata.live.db").write_text("", encoding="utf-8")
        with open(self.user_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "storage": {
                        "data_dir": str(data_dir),
                        "metadata_path": str(data_dir / "metadata.db"),
                    }
                },
                handle,
            )
        with mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False):
            config = load_config(self.paths, safe_mode=False)
        self.assertEqual(str(config.get("storage", {}).get("metadata_path") or ""), str(data_dir / "metadata.live.db"))

    def test_explicit_metadata_env_override_wins(self):
        data_dir = Path(self.tempdir.name) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        override = data_dir / "custom-metadata.db"
        with open(self.user_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "storage": {
                        "data_dir": str(data_dir),
                        "metadata_path": str(data_dir / "metadata.db"),
                    }
                },
                handle,
            )
        with mock.patch.dict(os.environ, {"AUTOCAPTURE_STORAGE_METADATA_PATH": str(override)}, clear=False):
            config = load_config(self.paths, safe_mode=False)
        self.assertEqual(str(config.get("storage", {}).get("metadata_path") or ""), str(override))

    def test_metadata_only_enables_minimal_query_plugin_profile(self):
        with mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False):
            config = load_config(self.paths, safe_mode=False)
        plugins = config.get("plugins", {}) if isinstance(config.get("plugins", {}), dict) else {}
        kernel = config.get("kernel", {}) if isinstance(config.get("kernel", {}), dict) else {}
        retrieval = config.get("retrieval", {}) if isinstance(config.get("retrieval", {}), dict) else {}
        required = kernel.get("safe_mode_required_capabilities", [])
        self.assertTrue(bool(plugins.get("safe_mode", False)))
        self.assertTrue(bool(plugins.get("safe_mode_minimal", False)))
        self.assertIn("retrieval.strategy", required)
        self.assertIn("answer.builder", required)
        self.assertFalse(bool(retrieval.get("vector_enabled", True)))


if __name__ == "__main__":
    unittest.main()
