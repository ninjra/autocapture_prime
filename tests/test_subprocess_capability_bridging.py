import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.plugin_system.registry import PluginRegistry


def _default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_storage_plugin(root: Path) -> str:
    plugin_id = "test.storage.stub"
    plugin_dir = root / "a_storage_stub"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class Store:\n"
        "    def __init__(self):\n"
        "        self._data = {\"k\": {\"value\": 1}}\n"
        "    def get(self, key, default=None):\n"
        "        return self._data.get(key, default)\n"
        "    def keys(self):\n"
        "        return list(self._data.keys())\n"
        "\n"
        "class Plugin:\n"
        "    def __init__(self, plugin_id, context):\n"
        "        self._store = Store()\n"
        "    def capabilities(self):\n"
        "        return {\"storage.metadata\": self._store}\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return Plugin(plugin_id, context)\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {"kind": "storage.metadata", "id": "default", "path": "plugin.py", "callable": "create_plugin"}
        ],
        "permissions": {"filesystem": "readwrite", "gpu": False, "raw_input": False, "network": False},
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "required_capabilities": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return plugin_id


def _write_consumer_plugin(root: Path, *, required_capabilities: list[str]) -> str:
    plugin_id = "test.consumer.subproc"
    plugin_dir = root / "b_consumer"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class Consumer:\n"
        "    def __init__(self, plugin_id, context):\n"
        "        self._context = context\n"
        "    def capabilities(self):\n"
        "        return {\"consumer.cap\": self}\n"
        "    def read(self, key):\n"
        "        store = self._context.get_capability(\"storage.metadata\")\n"
        "        return store.get(key)\n"
        "    def read_other(self):\n"
        "        other = self._context.get_capability(\"other.cap\")\n"
        "        return other.ping()\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return Consumer(plugin_id, context)\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {"kind": "consumer.cap", "id": "default", "path": "plugin.py", "callable": "create_plugin"}
        ],
        "permissions": {"filesystem": "read", "gpu": False, "raw_input": False, "network": False},
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "required_capabilities": required_capabilities,
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return plugin_id


def _write_bytes_plugin(root: Path) -> str:
    plugin_id = "test.bytes.subproc"
    plugin_dir = root / "c_bytes"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class BytesCap:\n"
        "    def get_bytes(self):\n"
        "        return b\"\\x00\\x01\"\n"
        "\n"
        "class Plugin:\n"
        "    def __init__(self, plugin_id, context):\n"
        "        self._cap = BytesCap()\n"
        "    def capabilities(self):\n"
        "        return {\"bytes.cap\": self._cap}\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return Plugin(plugin_id, context)\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {"kind": "bytes.cap", "id": "default", "path": "plugin.py", "callable": "create_plugin"}
        ],
        "permissions": {"filesystem": "read", "gpu": False, "raw_input": False, "network": False},
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "required_capabilities": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return plugin_id


class SubprocessCapabilityBridgingTests(unittest.TestCase):
    def test_subprocess_plugin_can_call_allowed_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage_id = _write_storage_plugin(root)
            consumer_id = _write_consumer_plugin(root, required_capabilities=["storage.metadata"])

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [storage_id, consumer_id]
            plugins["enabled"] = {storage_id: True, consumer_id: True}
            plugins["default_pack"] = [storage_id, consumer_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"
            hosting["inproc_allowlist"] = [storage_id]
            hosting["inproc_justifications"] = {storage_id: "test inproc storage capability"}
            hosting["rpc_timeout_s"] = 5
            hosting["rpc_max_message_bytes"] = 2_000_000
            hosting["sanitize_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            registry = PluginRegistry(config, safe_mode=False)
            _loaded, caps = registry.load_plugins()
            consumer = caps.get("consumer.cap")
            result = consumer.read("k")
            self.assertEqual(result, {"value": 1})

    def test_subprocess_plugin_blocks_unallowed_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage_id = _write_storage_plugin(root)
            consumer_id = _write_consumer_plugin(root, required_capabilities=["storage.metadata"])

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [storage_id, consumer_id]
            plugins["enabled"] = {storage_id: True, consumer_id: True}
            plugins["default_pack"] = [storage_id, consumer_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"
            hosting["inproc_allowlist"] = [storage_id]
            hosting["inproc_justifications"] = {storage_id: "test inproc storage capability"}
            hosting["rpc_timeout_s"] = 5
            hosting["rpc_max_message_bytes"] = 2_000_000
            hosting["sanitize_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            registry = PluginRegistry(config, safe_mode=False)
            _loaded, caps = registry.load_plugins()
            consumer = caps.get("consumer.cap")
            with self.assertRaises(PluginError):
                consumer.read_other()

    def test_subprocess_plugin_returns_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bytes_id = _write_bytes_plugin(root)

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [bytes_id]
            plugins["enabled"] = {bytes_id: True}
            plugins["default_pack"] = [bytes_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"
            hosting["inproc_allowlist"] = []
            hosting["rpc_timeout_s"] = 5
            hosting["rpc_max_message_bytes"] = 2_000_000
            hosting["sanitize_env"] = True
            hosting["cache_dir"] = str(root / "cache")

            registry = PluginRegistry(config, safe_mode=False)
            _loaded, caps = registry.load_plugins()
            bytes_cap = caps.get("bytes.cap")
            self.assertEqual(bytes_cap.get_bytes(), b"\x00\x01")


if __name__ == "__main__":
    unittest.main()
