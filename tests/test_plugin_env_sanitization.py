import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.registry import PluginRegistry


def _default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_env_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "import os\n"
        "\n"
        "class EnvPlugin:\n"
        "    def capabilities(self):\n"
        "        return {\"env.cap\": self}\n"
        "\n"
        "    def get(self, key):\n"
        "        return os.environ.get(key)\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return EnvPlugin()\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {"kind": "env.cap", "id": "main", "path": "plugin.py", "callable": "create_plugin"}
        ],
        "provides": ["env.cap"],
        "permissions": {"filesystem": "none", "gpu": False, "raw_input": False, "network": False},
        "required_capabilities": [],
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class EnvSanitizationTests(unittest.TestCase):
    def test_env_is_sanitized(self) -> None:
        # MOD-021 low-resource mode forces in-proc hosting for WSL stability; in that
        # mode we intentionally avoid spawning subprocess plugin hosts.
        if os.getenv("AUTOCAPTURE_PLUGINS_HOSTING_MODE", "").strip().lower() == "inproc":
            self.skipTest("subprocess hosting disabled in this environment")
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            plugin_id = "test.env.sanitize"
            _write_env_plugin(root, plugin_id)

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [plugin_id]
            plugins["enabled"] = {plugin_id: True}
            plugins["default_pack"] = [plugin_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"
            hosting["inproc_allowlist"] = []
            hosting["rpc_timeout_s"] = 2
            hosting["rpc_max_message_bytes"] = 2_000_000
            hosting["sanitize_env"] = True
            hosting["offline_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            original_hosting_mode = os.environ.get("AUTOCAPTURE_PLUGINS_HOSTING_MODE")
            original_proxy = os.environ.get("HTTP_PROXY")
            os.environ["HTTP_PROXY"] = "http://example.invalid"
            os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = "subprocess"
            try:
                registry = PluginRegistry(config, safe_mode=False)
                _loaded, caps = registry.load_plugins()
                env_cap = caps.get("env.cap")
                self.assertIsNone(env_cap.get("HTTP_PROXY"))
                # Subprocess hosts use per-plugin cache dirs under the configured base.
                self.assertEqual(env_cap.get("XDG_CACHE_HOME"), str(root / "cache" / plugin_id))
                self.assertEqual(env_cap.get("HF_HUB_OFFLINE"), "1")
            finally:
                if original_hosting_mode is None:
                    os.environ.pop("AUTOCAPTURE_PLUGINS_HOSTING_MODE", None)
                else:
                    os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = original_hosting_mode
                if original_proxy is None:
                    os.environ.pop("HTTP_PROXY", None)
                else:
                    os.environ["HTTP_PROXY"] = original_proxy


if __name__ == "__main__":
    unittest.main()
