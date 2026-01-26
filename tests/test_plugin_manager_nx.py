import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.manager import PluginManager


class PluginManagerNXTests(unittest.TestCase):
    def test_list_plugins_and_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            config.setdefault("paths", {})["config_dir"] = tmp
            manager = PluginManager(config, safe_mode=False)
            statuses = manager.list_plugins()
            self.assertTrue(statuses)

            target = statuses[0].plugin_id
            manager.disable(target)
            user_cfg = json.loads((Path(tmp) / "user.json").read_text(encoding="utf-8"))
            self.assertFalse(user_cfg["plugins"]["enabled"][target])

            manager.enable(target)
            user_cfg = json.loads((Path(tmp) / "user.json").read_text(encoding="utf-8"))
            self.assertTrue(user_cfg["plugins"]["enabled"][target])


if __name__ == "__main__":
    unittest.main()
