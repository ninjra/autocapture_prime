import json
import tempfile
import unittest

from autocapture_nx.plugin_system.manager import PluginManager


class PluginLifecycleStateMachineTests(unittest.TestCase):
    def test_enable_requires_approval_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "paths": {"config_dir": tmp},
                "plugins": {
                    "approvals": {"required": True},
                    "locks": {"enforce": False},
                },
            }
            mgr = PluginManager(cfg, safe_mode=False)
            plugins = mgr.list_plugins()
            self.assertTrue(plugins, "expected at least one builtin plugin manifest")
            plugin_id = plugins[0].plugin_id

            with self.assertRaises(RuntimeError) as ctx:
                mgr.enable(plugin_id)
            self.assertIn("plugin_not_approved", str(ctx.exception))

            digest = mgr.permissions_digest(plugin_id)
            self.assertTrue(digest.get("ok"))
            accept = str(digest.get("digest") or "")
            result = mgr.approve_permissions_confirm(
                plugin_id,
                accept_digest=accept,
                confirm=f"APPROVE:{plugin_id}",
            )
            self.assertTrue(result.get("ok"), result)

            # Now enable should succeed.
            mgr.enable(plugin_id)
            state = mgr.lifecycle_state(plugin_id)
            self.assertTrue(state.get("ok"))
            self.assertTrue(state.get("approved"))
            self.assertTrue(state.get("enabled"))

            user_path = mgr._user_config_path()  # noqa: SLF001
            user_cfg = json.loads(user_path.read_text(encoding="utf-8"))
            self.assertIn(plugin_id, user_cfg.get("plugins", {}).get("approvals", {}))


if __name__ == "__main__":
    unittest.main()

