import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.kernel.errors import PermissionError
from autocapture_nx.plugin_system.registry import PluginRegistry


def _write_network_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(plugin_dir / "plugin.py", "w", encoding="utf-8") as handle:
        handle.write(
            "def create_plugin(plugin_id, context):\n"
            "    class P:\n"
            "        def capabilities(self):\n"
            "            return {\"test.capability\": self}\n"
            "        def ping(self):\n"
            "            import socket\n"
            "            socket.socket()\n"
            "    return P()\n"
        )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {
                "kind": "test",
                "id": "default",
                "path": "plugin.py",
                "callable": "create_plugin",
            }
        ],
        "permissions": {
            "filesystem": "read",
            "gpu": False,
            "raw_input": False,
            "network": False,
        },
        "compat": {"requires_kernel": ">=0.1.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    with open(plugin_dir / "plugin.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


class PluginNetworkBlockTests(unittest.TestCase):
    def test_capability_network_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_network_plugin(plugin_root, "local.blocked.plugin")

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

            override = {
                "plugins": {
                    "allowlist": ["local.blocked.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                }
            }
            with open(user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            paths = ConfigPaths(default_path, user_path, schema_path, backup_dir)
            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, caps = registry.load_plugins()
            cap = caps.get("test.capability")
            with self.assertRaises(PermissionError):
                cap.ping()


if __name__ == "__main__":
    unittest.main()
