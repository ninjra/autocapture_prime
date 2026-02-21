import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.plugin_system.registry import PluginRegistry


def _default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_echo_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class EchoPlugin:\n"
        "    def capabilities(self):\n"
        "        return {\"echo.cap\": self}\n"
        "\n"
        "    def echo(self, value):\n"
        "        return value\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return EchoPlugin()\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {"kind": "plugin", "id": "main", "path": "plugin.py", "callable": "create_plugin"}
        ],
        "permissions": {"filesystem": "none", "gpu": False, "raw_input": False, "network": False},
        "required_capabilities": [],
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class RpcSizeLimitTests(unittest.TestCase):
    def test_rpc_message_size_limit(self) -> None:
        # This test validates subprocess RPC framing limits. Under the low-resource
        # WSL harness we force in-proc hosting for stability, where there is no
        # subprocess RPC boundary to enforce a max message size.
        if os.environ.get("AUTOCAPTURE_PLUGINS_HOSTING_MODE", "").strip().lower() == "inproc":
            self.skipTest("subprocess-only: rpc_max_message_bytes is enforced in host_runner IPC")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_id = "test.rpc.size"
            _write_echo_plugin(root, plugin_id)

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
            hosting["rpc_max_message_bytes"] = 200
            hosting["sanitize_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            original_hosting_mode = os.environ.get("AUTOCAPTURE_PLUGINS_HOSTING_MODE")
            os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = "subprocess"
            try:
                registry = PluginRegistry(config, safe_mode=False)
                _loaded, caps = registry.load_plugins()
                echo = caps.get("echo.cap")
                big_payload = "x" * 400
                with self.assertRaises(PluginError):
                    echo.echo(big_payload)
            finally:
                if original_hosting_mode is None:
                    os.environ.pop("AUTOCAPTURE_PLUGINS_HOSTING_MODE", None)
                else:
                    os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = original_hosting_mode


if __name__ == "__main__":
    unittest.main()
