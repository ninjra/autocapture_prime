import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.registry import PluginRegistry


def _write_temp_plugin(root: Path, plugin_id: str, capability: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    os.makedirs(plugin_dir, exist_ok=True)
    plugin_dir.joinpath("plugin.py").write_text(
        (
            "def create_plugin(plugin_id, context):\n"
            "    class P:\n"
            "        def capabilities(self):\n"
            f"            return {{\"{capability}\": self}}\n"
            "        def whoami(self):\n"
            "            return plugin_id\n"
            "    return P()\n"
        ),
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {
                "kind": "test.kind",
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
    plugin_dir.joinpath("plugin.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _base_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


class CapabilityPolicyTests(unittest.TestCase):
    def test_single_mode_rejects_duplicate_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap = "test.capability"
            p1 = "local.test.one"
            p2 = "local.test.two"
            _write_temp_plugin(root, p1, cap)
            _write_temp_plugin(root, p2, cap)

            config = _base_config()
            config["plugins"]["allowlist"] = [p1, p2]
            config["plugins"]["enabled"] = {p1: True, p2: True}
            config["plugins"]["search_paths"] = [str(root)]
            config["plugins"]["locks"]["enforce"] = False
            config.setdefault("storage", {})["audit_db_path"] = str(root / "audit.db")
            config["plugins"]["capabilities"][cap] = {
                "mode": "single",
                "preferred": [],
                "provider_ids": [],
                "fanout": True,
                "max_providers": 1,
            }

            registry = PluginRegistry(config, safe_mode=False)
            _plugins, caps = registry.load_plugins()
            selected = caps.get(cap)
            self.assertEqual(selected.whoami(), p1)

    def test_single_mode_uses_preferred_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap = "test.capability"
            p1 = "local.test.one"
            p2 = "local.test.two"
            _write_temp_plugin(root, p1, cap)
            _write_temp_plugin(root, p2, cap)

            config = _base_config()
            config["plugins"]["allowlist"] = [p1, p2]
            config["plugins"]["enabled"] = {p1: True, p2: True}
            config["plugins"]["search_paths"] = [str(root)]
            config["plugins"]["locks"]["enforce"] = False
            config.setdefault("storage", {})["audit_db_path"] = str(root / "audit.db")
            config["plugins"]["capabilities"][cap] = {
                "mode": "single",
                "preferred": [p2],
                "provider_ids": [],
                "fanout": True,
                "max_providers": 1,
            }

            registry = PluginRegistry(config, safe_mode=False)
            _plugins, caps = registry.load_plugins()
            selected = caps.get(cap)
            self.assertEqual(selected.whoami(), p2)

    def test_multi_mode_exposes_all_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap = "test.capability"
            p1 = "local.test.one"
            p2 = "local.test.two"
            _write_temp_plugin(root, p1, cap)
            _write_temp_plugin(root, p2, cap)

            config = _base_config()
            config["plugins"]["allowlist"] = [p1, p2]
            config["plugins"]["enabled"] = {p1: True, p2: True}
            config["plugins"]["search_paths"] = [str(root)]
            config["plugins"]["locks"]["enforce"] = False
            config.setdefault("storage", {})["audit_db_path"] = str(root / "audit.db")
            config["plugins"]["capabilities"][cap] = {
                "mode": "multi",
                "preferred": [],
                "provider_ids": [],
                "fanout": True,
                "max_providers": 4,
            }

            registry = PluginRegistry(config, safe_mode=False)
            _plugins, caps = registry.load_plugins()
            multi = caps.get(cap)
            self.assertEqual(set(multi.provider_ids()), {p1, p2})


if __name__ == "__main__":
    unittest.main()
