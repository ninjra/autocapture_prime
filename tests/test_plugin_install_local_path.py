import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.manager import PluginManager


def _load_template_manifest() -> dict:
    # Use a builtin manifest as a schema/compat template to avoid drift.
    template = Path("plugins/builtin/ocr_stub/plugin.json")
    return json.loads(template.read_text(encoding="utf-8"))


class PluginInstallLocalPathTests(unittest.TestCase):
    def test_install_local_dir_dry_run_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            lockfile = cfg_dir / "plugin_locks.json"
            plugin_root = Path(tmp) / "local_plugin"
            plugin_root.mkdir(parents=True, exist_ok=True)
            manifest = _load_template_manifest()
            manifest["plugin_id"] = "local.test.plugin"
            manifest["version"] = "0.0.0-test"
            (plugin_root / "plugin.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            (plugin_root / "plugin.py").write_text(
                "def create_plugin(plugin_id, ctx):\n    return object()\n",
                encoding="utf-8",
            )

            cfg = {
                "paths": {"config_dir": str(cfg_dir)},
                "plugins": {"locks": {"lockfile": str(lockfile), "enforce": False}},
            }
            mgr = PluginManager(cfg, safe_mode=False)

            preview = mgr.install_local(str(plugin_root), dry_run=True)
            self.assertTrue(preview.get("ok"), preview)
            self.assertTrue(preview.get("preview", {}).get("dry_run"))

            applied = mgr.install_local(str(plugin_root), dry_run=False)
            self.assertTrue(applied.get("ok"), applied)
            self.assertTrue(applied.get("installed"))

            user_path = cfg_dir / "user.json"
            self.assertTrue(user_path.exists())
            user_cfg = json.loads(user_path.read_text(encoding="utf-8"))
            search_paths = user_cfg.get("plugins", {}).get("search_paths", [])
            self.assertIn(str(plugin_root), [str(p) for p in search_paths])

            locks = json.loads(lockfile.read_text(encoding="utf-8")).get("plugins", {})
            self.assertIn("local.test.plugin", locks)
            self.assertIn("manifest_sha256", locks["local.test.plugin"])
            self.assertIn("artifact_sha256", locks["local.test.plugin"])


if __name__ == "__main__":
    unittest.main()

