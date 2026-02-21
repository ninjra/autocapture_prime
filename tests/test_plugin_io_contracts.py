import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.plugin_system.registry import PluginRegistry


def _write_stage_plugin(root: Path, plugin_id: str, *, result_expr: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(plugin_dir / "plugin.py", "w", encoding="utf-8") as handle:
        handle.write(
            "class P:\n"
            "    def __init__(self, context):\n"
            "        self.settings = context.config\n"
            "    def capabilities(self):\n"
            "        return {\"processing.stage.hooks\": self}\n"
            "    def stages(self):\n"
            "        return [\"temporal.segment\"]\n"
            "    def run_stage(self, stage, payload):\n"
            f"        {result_expr}\n"
            "def create_plugin(plugin_id, context):\n"
            "    return P(context)\n"
        )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {
                "kind": "processing.stage.hooks",
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
        "required_capabilities": [],
        "compat": {"requires_kernel": ">=0.1.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    with open(plugin_dir / "plugin.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


def _storage_override(root: Path) -> dict:
    data_dir = root / "data"
    vault_dir = data_dir / "vault"
    return {
        "paths": {
            "config_dir": str(root),
            "data_dir": str(data_dir),
        },
        "storage": {
            "data_dir": str(data_dir),
            "crypto": {
                "keyring_path": str(vault_dir / "keyring.json"),
                "root_key_path": str(vault_dir / "root.key"),
            },
        }
    }


def _config_paths(root: Path) -> ConfigPaths:
    default_path = root / "default.json"
    user_path = root / "user.json"
    schema_path = root / "schema.json"
    backup_dir = root / "backup"
    with open("config/default.json", "r", encoding="utf-8") as handle:
        default = json.load(handle)
    with open(default_path, "w", encoding="utf-8") as handle:
        json.dump(default, handle, indent=2, sort_keys=True)
    with open("contracts/config_schema.json", "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    with open(schema_path, "w", encoding="utf-8") as handle:
        json.dump(schema, handle, indent=2, sort_keys=True)
    return ConfigPaths(default_path, user_path, schema_path, backup_dir)


class PluginIOContractTests(unittest.TestCase):
    def test_stage_hook_output_schema_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_stage_plugin(plugin_root, "local.stage.bad", result_expr="return {\"tokens\": \"bad\"}")

            paths = _config_paths(root)
            override = {
                **_storage_override(root),
                "plugins": {
                    "allowlist": ["local.stage.bad"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            _plugins, caps = registry.load_plugins()
            stage_hooks = caps.get("processing.stage.hooks")
            results = stage_hooks.run_stage("temporal.segment", {"run_id": "run"})
            self.assertIsInstance(results, list)
            self.assertTrue(
                any(
                    (not item.get("ok"))
                    and "I/O contract output invalid" in str(item.get("error", ""))
                    for item in results
                )
            )


if __name__ == "__main__":
    unittest.main()
