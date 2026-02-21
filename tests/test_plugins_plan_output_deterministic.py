import re
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.manager import PluginManager


class PluginsPlanDeterminismTests(unittest.TestCase):
    def test_plan_is_stable_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "paths": {"config_dir": str(Path(tmp) / "cfg")},
                "plugins": {"locks": {"enforce": False}},
            }
            mgr = PluginManager(cfg, safe_mode=False)
            a = mgr.plugins_plan()
            b = mgr.plugins_plan()
            self.assertEqual(a, b)
            plan_hash = str(a.get("plan_hash") or "")
            self.assertTrue(re.fullmatch(r"[a-f0-9]{64}", plan_hash), plan_hash)
            self.assertTrue(isinstance(a.get("capabilities"), dict))


if __name__ == "__main__":
    unittest.main()

