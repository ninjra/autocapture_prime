import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.plugin_system.registry import PluginRegistry


def _default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_fs_plugin(root: Path, plugin_id: str, allowed_root: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class FSPlugin:\n"
        "    def capabilities(self):\n"
        "        return {\"fs.cap\": self}\n"
        "\n"
        "    def read_text(self, path):\n"
        "        with open(path, 'r', encoding='utf-8') as handle:\n"
        "            return handle.read()\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return FSPlugin()\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {"kind": "plugin", "id": "main", "path": "plugin.py", "callable": "create_plugin"}
        ],
        "permissions": {"filesystem": "read", "gpu": False, "raw_input": False, "network": False},
        "required_capabilities": [],
        "filesystem_policy": {"read": [allowed_root], "readwrite": []},
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class FilesystemPolicyTests(unittest.TestCase):
    def test_filesystem_policy_blocks_outside_roots(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            allowed_dir = root / "allowed"
            denied_dir = root / "denied"
            allowed_dir.mkdir(parents=True, exist_ok=True)
            denied_dir.mkdir(parents=True, exist_ok=True)
            allowed_file = allowed_dir / "ok.txt"
            denied_file = denied_dir / "nope.txt"
            allowed_file.write_text("ok", encoding="utf-8")
            denied_file.write_text("nope", encoding="utf-8")

            plugin_id = "test.fs.policy"
            _write_fs_plugin(root, plugin_id, str(allowed_dir))

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [plugin_id]
            plugins["enabled"] = {plugin_id: True}
            plugins["default_pack"] = [plugin_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            plugins["filesystem_defaults"] = {"read": [], "readwrite": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"
            hosting["inproc_allowlist"] = []
            hosting["rpc_timeout_s"] = 2
            hosting["rpc_max_message_bytes"] = 2_000_000
            hosting["sanitize_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            registry = PluginRegistry(config, safe_mode=False)
            _loaded, caps = registry.load_plugins()
            fs_cap = caps.get("fs.cap")
            self.assertEqual(fs_cap.read_text(str(allowed_file)), "ok")
            with self.assertRaises(PluginError):
                fs_cap.read_text(str(denied_file))

    def test_filesystem_policy_expands_anchor_dir(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            anchor_dir = root / "anchor_store"
            anchor_path = anchor_dir / "anchors.ndjson"
            config = _default_config()
            storage = config.setdefault("storage", {})
            storage["data_dir"] = str(root / "data")
            storage["anchor"] = {"path": str(anchor_path), "use_dpapi": False}
            plugins = config.setdefault("plugins", {})
            plugins["filesystem_defaults"] = {"read": [], "readwrite": []}
            plugins["filesystem_policies"] = {
                "test.anchor.policy": {"readwrite": ["{anchor_dir}"]}
            }
            plugin_root = root / "plugin"
            plugin_root.mkdir(parents=True, exist_ok=True)
            manifest = {"plugin_id": "test.anchor.policy", "permissions": {"filesystem": "readwrite"}}
            registry = PluginRegistry(config, safe_mode=False)
            policy = registry._filesystem_policy("test.anchor.policy", manifest, plugin_root)
            self.assertIsNotNone(policy)
            self.assertIn(anchor_dir.resolve(), list(policy.readwrite_roots))


if __name__ == "__main__":
    unittest.main()
