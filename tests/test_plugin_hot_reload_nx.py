import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
from autocapture_nx.plugin_system.registry import PluginRegistry


class PluginHotReloadTests(unittest.TestCase):
    def test_hot_reload_requires_lock_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "mx_hot"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            module_path = plugin_dir / "plugin.py"
            manifest_path = plugin_dir / "plugin.json"
            lockfile = root / "plugin_locks.json"

            module_path.write_text(
                textwrap.dedent(
                    """
                    class HotPlugin:
                        def __init__(self, plugin_id, context):
                            self.value = "v1"
                            self.closed = False
                        def capabilities(self):
                            return {"hot.cap": self}
                        def get_value(self):
                            return self.value
                        def close(self):
                            self.closed = True

                    def create_plugin(plugin_id, context):
                        return HotPlugin(plugin_id, context)
                    """
                ).strip(),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "compat": {"requires_kernel": ">=0.1.0", "requires_schema_versions": [1]},
                        "depends_on": [],
                        "enabled": True,
                        "entrypoints": [
                            {
                                "callable": "create_plugin",
                                "id": "default",
                                "kind": "hot.cap",
                                "path": "plugin.py",
                            }
                        ],
                        "hash_lock": {"artifact_sha256": "", "manifest_sha256": ""},
                        "permissions": {
                            "filesystem": "none",
                            "gpu": False,
                            "network": False,
                            "raw_input": False,
                        },
                        "plugin_id": "mx.hot",
                        "required_capabilities": [],
                        "version": "0.1.0",
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            def write_lock():
                lock_payload = {
                    "version": 1,
                    "generated_at": "now",
                    "plugins": {
                        "mx.hot": {
                            "manifest_sha256": sha256_file(manifest_path),
                            "artifact_sha256": sha256_directory(plugin_dir),
                        }
                    },
                }
                lockfile.write_text(json.dumps(lock_payload, indent=2, sort_keys=True), encoding="utf-8")

            write_lock()

            config = {
                "plugins": {
                    "allowlist": ["mx.hot"],
                    "enabled": {"mx.hot": True},
                    "default_pack": [],
                    "search_paths": [str(root)],
                    "locks": {"enforce": True, "lockfile": str(lockfile)},
                    "hosting": {
                        "mode": "inproc",
                        "inproc_allowlist": ["mx.hot"],
                        "inproc_justifications": {"mx.hot": "test"},
                        "rpc_timeout_s": 1,
                        "rpc_max_message_bytes": 100000,
                        "sanitize_env": True,
                        "cache_dir": "data/cache/plugins",
                    },
                    "permissions": {"network_allowed_plugin_ids": []},
                    "conflicts": {"enforce": True, "allow_pairs": []},
                    "capabilities": {},
                    "safe_mode": False,
                    "meta": {"configurator_allowed": [], "policy_allowed": []},
                    "filesystem_defaults": {"read": [], "readwrite": []},
                    "filesystem_policies": {},
                    "hot_reload": {"enabled": True, "allowlist": ["mx.hot"], "blocklist": []},
                }
            }

            registry = PluginRegistry(config, safe_mode=False)
            loaded, caps = registry.load_plugins()
            self.assertEqual(caps.get("hot.cap").get_value(), "v1")
            old_instance = loaded[0].instance

            module_path.write_text(
                textwrap.dedent(
                    """
                    class HotPlugin:
                        def __init__(self, plugin_id, context):
                            self.value = "v2"
                            self.closed = False
                        def capabilities(self):
                            return {"hot.cap": self}
                        def get_value(self):
                            return self.value
                        def close(self):
                            self.closed = True

                    def create_plugin(plugin_id, context):
                        return HotPlugin(plugin_id, context)
                    """
                ).strip(),
                encoding="utf-8",
            )

            with self.assertRaises(Exception):
                registry.hot_reload(loaded, plugin_ids=["mx.hot"])

            write_lock()
            reloaded, new_caps, report = registry.hot_reload(loaded, plugin_ids=["mx.hot"])
            self.assertIn("mx.hot", report.get("reloaded", []))
            self.assertTrue(old_instance.closed)
            self.assertEqual(new_caps.get("hot.cap").get_value(), "v2")


if __name__ == "__main__":
    unittest.main()
