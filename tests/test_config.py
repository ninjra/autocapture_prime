import json
import shutil
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
