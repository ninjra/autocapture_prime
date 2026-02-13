import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.manager import PluginManager


class PluginPermissionPromptRequiredTests(unittest.TestCase):
    def test_high_risk_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "paths": {"config_dir": str(Path(tmp) / "cfg")},
                "plugins": {
                    "locks": {"enforce": False},
                    "approvals": {"required": True},
                },
            }
            mgr = PluginManager(cfg, safe_mode=False)
            plugins = mgr.list_plugins()
            self.assertTrue(plugins)
            # Pick a plugin that requests filesystem or network permissions (most do).
            target = None
            for row in plugins:
                perms = row.permissions or {}
                if perms.get("network") or perms.get("filesystem"):
                    target = row.plugin_id
                    break
            self.assertTrue(target)

            digest = mgr.permissions_digest(target)
            self.assertTrue(digest.get("ok"))
            accept = str(digest.get("digest") or "")

            denied = mgr.approve_permissions_confirm(target, accept_digest=accept, confirm="")
            self.assertFalse(denied.get("ok"))
            self.assertEqual(denied.get("error"), "confirmation_required")
            required = str(denied.get("required") or "")
            self.assertTrue(required.startswith("APPROVE:"))

            ok = mgr.approve_permissions_confirm(target, accept_digest=accept, confirm=required)
            self.assertTrue(ok.get("ok"), ok)


if __name__ == "__main__":
    unittest.main()

