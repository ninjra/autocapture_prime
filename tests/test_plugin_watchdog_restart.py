import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.plugin_system.registry import PluginRegistry


def _default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_slow_plugin(root: Path, plugin_id: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "import time\n"
        "\n"
        "class SlowPlugin:\n"
        "    def capabilities(self):\n"
        "        return {\"slow.cap\": self}\n"
        "\n"
        "    def sleep(self, seconds):\n"
        "        time.sleep(seconds)\n"
        "        return {\"slept\": seconds}\n"
        "\n"
        "    def ping(self):\n"
        "        return {\"ok\": True}\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return SlowPlugin()\n",
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


class PluginWatchdogTests(unittest.TestCase):
    def test_watchdog_restarts_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            plugin_id = "test.slow.watchdog"
            _write_slow_plugin(root, plugin_id)

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
            hosting["rpc_timeout_s"] = 0.2
            hosting["rpc_timeout_limit"] = 1
            hosting["rpc_timeout_window_s"] = 5
            hosting["rpc_watchdog_restart_max"] = 2
            hosting["rpc_watchdog_backoff_s"] = 0.0
            hosting["rpc_max_message_bytes"] = 2_000_000
            hosting["sanitize_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            original_hosting_mode = os.environ.get("AUTOCAPTURE_PLUGINS_HOSTING_MODE")
            os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = "subprocess"
            try:
                registry = PluginRegistry(config, safe_mode=False)
                _loaded, caps = registry.load_plugins()
                slow = caps.get("slow.cap")
                with self.assertRaises(PluginError):
                    slow.sleep(1.0)
                self.assertEqual(slow.ping(), {"ok": True})
            finally:
                if original_hosting_mode is None:
                    os.environ.pop("AUTOCAPTURE_PLUGINS_HOSTING_MODE", None)
                else:
                    os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = original_hosting_mode


if __name__ == "__main__":
    unittest.main()
