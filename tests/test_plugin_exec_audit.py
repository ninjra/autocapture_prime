import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.plugin_system.registry import PluginRegistry


def _write_echo_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(plugin_dir / "plugin.py", "w", encoding="utf-8") as handle:
        handle.write(
            "class P:\n"
            "    def __init__(self, context):\n"
            "        self.settings = context.config\n"
            "    def capabilities(self):\n"
            "        return {\"test.echo\": self}\n"
            "    def echo(self, value):\n"
            "        return {\"value\": value}\n"
            "def create_plugin(plugin_id, context):\n"
            "    return P(context)\n"
        )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {
                "kind": "test.echo",
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


class PluginExecAuditTests(unittest.TestCase):
    def test_plugin_exec_records_audit_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_echo_plugin(plugin_root, "local.echo.plugin")

            audit_path = root / "audit.db"
            data_dir = root / "data"
            paths = _config_paths(root)
            override = {
                "paths": {"config_dir": str(root), "data_dir": str(data_dir)},
                "storage": {"data_dir": str(data_dir), "audit_db_path": str(audit_path)},
                "runtime": {"run_id": "run-test"},
                "plugins": {
                    "allowlist": ["local.echo.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            _plugins, caps = registry.load_plugins()
            echo = caps.get("test.echo")
            echo.echo("hello")

            conn = sqlite3.connect(str(audit_path))
            row = conn.execute(
                "SELECT plugin_id, capability, method, ok FROM plugin_exec_audit WHERE plugin_id = ?",
                ("local.echo.plugin",),
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "local.echo.plugin")
            self.assertEqual(row[1], "test.echo")
            self.assertEqual(row[2], "echo")
            self.assertEqual(row[3], 1)


if __name__ == "__main__":
    unittest.main()
