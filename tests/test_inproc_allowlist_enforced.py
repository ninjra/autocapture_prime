import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.registry import PluginRegistry


class InprocAllowlistEnforcedTests(unittest.TestCase):
    def test_inproc_mode_refuses_non_allowlisted_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            # Pick a builtin plugin id that exists.
            plugin_id = "builtin.ocr.basic"
            config = {
                "paths": {"config_dir": str(cfg_dir)},
                "plugins": {
                    "allowlist": [plugin_id],
                    "enabled": {plugin_id: True},
                    "hosting": {
                        "mode": "inproc",
                        "inproc_allowlist": [],
                        "inproc_allow_all": False,
                        # Avoid WSL auto-fill behavior in this test by making it explicit.
                        "wsl_force_inproc": False,
                    },
                    "locks": {"enforce": False},
                },
                "storage": {"audit_db_path": str(Path(tmp) / "audit.db")},
            }
            reg = PluginRegistry(config, safe_mode=False)
            _loaded, _caps = reg.load_plugins()
            report = reg.load_report()
            self.assertIn(plugin_id, report.get("failed", []), report)
            errors = report.get("errors", [])
            self.assertTrue(any((e.get("plugin_id") == plugin_id and "inproc_not_allowlisted" in str(e.get("error", ""))) for e in errors if isinstance(e, dict)))


if __name__ == "__main__":
    unittest.main()

