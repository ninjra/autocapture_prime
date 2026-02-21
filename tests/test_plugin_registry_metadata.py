import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.plugin_system.registry import PluginRegistry


def _write_meta_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(plugin_dir / "plugin.py", "w", encoding="utf-8") as handle:
        handle.write(
            "class P:\n"
            "    def __init__(self, context):\n"
            "        self.settings = context.config\n"
            "    def capabilities(self):\n"
            "        return {\"test.meta\": self}\n"
            "    def ping(self):\n"
            "        return {\"ok\": True}\n"
            "def create_plugin(plugin_id, context):\n"
            "    return P(context)\n"
        )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {
                "kind": "test.meta",
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
        "capability_tags": ["fast", "local"],
        "provides": ["test.meta"],
    }
    with open(plugin_dir / "plugin.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


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


class PluginRegistryMetadataTests(unittest.TestCase):
    def test_registry_metadata_records_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            plugin_id = "local.meta.plugin"
            _write_meta_plugin(plugin_root, plugin_id)

            audit_path = root / "audit.db"
            data_dir = root / "data"
            paths = _config_paths(root)
            override = {
                "paths": {"config_dir": str(root), "data_dir": str(data_dir)},
                "storage": {"data_dir": str(data_dir), "audit_db_path": str(audit_path)},
                "runtime": {"run_id": "run-test"},
                "plugins": {
                    "allowlist": [plugin_id],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            registry.load_plugins()

            conn = sqlite3.connect(str(audit_path))
            row = conn.execute(
                "SELECT capability_tags, provides FROM plugin_registry_meta WHERE plugin_id = ?",
                (plugin_id,),
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            tags = json.loads(row[0])
            provides = json.loads(row[1])
            self.assertIn("fast", tags)
            self.assertIn("local", tags)
            self.assertIn("test.meta", provides)


if __name__ == "__main__":
    unittest.main()
