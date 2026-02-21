import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.plugin_system.registry import PluginRegistry


def _write_temp_plugin(
    root: Path,
    plugin_id: str,
    network: bool = False,
    compat: dict | None = None,
    *,
    settings_paths: list[str] | None = None,
    settings_schema: dict | None = None,
    settings_schema_path: str | None = None,
) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(plugin_dir / "plugin.py", "w", encoding="utf-8") as handle:
        handle.write(
            "class P:\n"
            "    def __init__(self, context):\n"
            "        self.settings = context.config\n"
            "    def capabilities(self):\n"
            "        return {}\n"
            "def create_plugin(plugin_id, context):\n"
            "    return P(context)\n"
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
            "network": network,
        },
        "required_capabilities": [],
        "compat": compat or {"requires_kernel": ">=0.1.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    if settings_paths:
        manifest["settings_paths"] = settings_paths
    if settings_schema is not None:
        manifest["settings_schema"] = settings_schema
    if settings_schema_path:
        manifest["settings_schema_path"] = settings_schema_path
    with open(plugin_dir / "plugin.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


def _write_crash_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(plugin_dir / "plugin.py", "w", encoding="utf-8") as handle:
        handle.write(
            "def create_plugin(plugin_id, context):\n"
            "    raise RuntimeError('boom')\n"
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


class PluginLoaderTests(unittest.TestCase):
    def _config_paths(self, root: Path) -> ConfigPaths:
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

    def test_allowlist_blocks_unlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_temp_plugin(plugin_root, "local.test.plugin")

            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "plugins": {
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                }
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin_ids = {p.plugin_id for p in plugins}
            self.assertNotIn("local.test.plugin", plugin_ids)

    def test_network_permission_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_temp_plugin(plugin_root, "local.net.plugin", network=True)

            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "plugins": {
                    "allowlist": ["local.net.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                }
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin_ids = {p.plugin_id for p in plugins}
            self.assertNotIn("local.net.plugin", plugin_ids)
            report = registry.load_report()
            self.assertIn("local.net.plugin", report.get("failed", []))

    def test_compat_version_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_temp_plugin(
                plugin_root,
                "local.compat.plugin",
                compat={"requires_kernel": ">=999.0.0", "requires_schema_versions": [1]},
            )

            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "plugins": {
                    "allowlist": ["local.compat.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin_ids = {p.plugin_id for p in plugins}
            self.assertNotIn("local.compat.plugin", plugin_ids)
            report = registry.load_report()
            self.assertIn("local.compat.plugin", report.get("failed", []))

    def test_disable_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "plugins": {"enabled": {"builtin.egress.gateway": False}}
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin_ids = {p.plugin_id for p in plugins}
            self.assertNotIn("builtin.egress.gateway", plugin_ids)

    def test_plugin_crash_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_crash_plugin(plugin_root, "local.crash.plugin")
            _write_temp_plugin(plugin_root, "local.ok.plugin")

            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "plugins": {
                    "allowlist": ["local.crash.plugin", "local.ok.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin_ids = {p.plugin_id for p in plugins}
            self.assertIn("local.ok.plugin", plugin_ids)
            self.assertNotIn("local.crash.plugin", plugin_ids)
            report = registry.load_report()
            self.assertIn("local.crash.plugin", report.get("failed", []))

    def test_plugin_settings_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_temp_plugin(plugin_root, "local.settings.plugin", settings_paths=["runtime"])

            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "runtime": {"timezone": "America/Denver"},
                "plugins": {
                    "allowlist": ["local.settings.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                    "settings": {"local.settings.plugin": {"runtime": {"timezone": "UTC"}}},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin = next(p for p in plugins if p.plugin_id == "local.settings.plugin")
            settings = getattr(plugin.instance, "settings", {})
            self.assertIsInstance(settings, dict)
            self.assertIn("runtime", settings)
            self.assertEqual(settings.get("runtime", {}).get("timezone"), "UTC")
            self.assertNotIn("storage", settings)

    def test_settings_schema_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins"
            os.makedirs(plugin_root, exist_ok=True)
            _write_temp_plugin(plugin_root, "local.schema.plugin", settings_paths=["runtime"])

            paths = self._config_paths(root)
            override = {
                **_storage_override(root),
                "runtime": {"timezone": "UTC"},
                "plugins": {
                    "allowlist": ["local.schema.plugin"],
                    "search_paths": [str(plugin_root)],
                    "locks": {"enforce": False, "lockfile": "config/plugin_locks.json"},
                    "settings": {"local.schema.plugin": {"runtime": {"timezone": 123}}},
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(override, handle)

            config = load_config(paths, safe_mode=False)
            registry = PluginRegistry(config, safe_mode=False)
            plugins, _caps = registry.load_plugins()
            plugin_ids = {p.plugin_id for p in plugins}
            self.assertNotIn("local.schema.plugin", plugin_ids)
            report = registry.load_report()
            self.assertIn("local.schema.plugin", report.get("failed", []))


if __name__ == "__main__":
    unittest.main()
