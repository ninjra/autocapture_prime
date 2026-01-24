import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


class SafeModeTests(unittest.TestCase):
    def test_safe_mode_ignores_user_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_path = root / "default.json"
            schema_path = root / "schema.json"
            user_path = root / "user.json"
            backup_dir = root / "backup"
            with open("config/default.json", "r", encoding="utf-8") as handle:
                default = json.load(handle)
            with open(default_path, "w", encoding="utf-8") as handle:
                json.dump(default, handle, indent=2, sort_keys=True)
            with open("contracts/config_schema.json", "r", encoding="utf-8") as handle:
                schema = json.load(handle)
            with open(schema_path, "w", encoding="utf-8") as handle:
                json.dump(schema, handle, indent=2, sort_keys=True)
            with open(user_path, "w", encoding="utf-8") as handle:
                json.dump({"plugins": {"enabled": {"builtin.egress.gateway": False}}}, handle)

            paths = ConfigPaths(default_path, user_path, schema_path, backup_dir)
            kernel = Kernel(paths, safe_mode=True)
            system = kernel.boot()
            plugin_ids = {p.plugin_id for p in system.plugins}
            self.assertIn("builtin.egress.gateway", plugin_ids)


if __name__ == "__main__":
    unittest.main()
