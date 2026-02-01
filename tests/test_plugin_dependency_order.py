import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.registry import PluginRegistry


def _default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_provider(root: Path, plugin_id: str, kind: str, provides: list[str] | None = None) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class Provider:\n"
        "    def ping(self):\n"
        "        return \"ok\"\n"
        "\n"
        "    def budget_snapshot(self):\n"
        "        return {\"remaining_ms\": 0}\n"
        "\n"
        "    def capabilities(self):\n"
        f"        return {{\"{kind}\": self}}\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        "    return Provider()\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [{"kind": kind, "id": "default", "path": "plugin.py", "callable": "create_plugin"}],
        "permissions": {"filesystem": "read", "gpu": False, "raw_input": False, "network": False},
        "required_capabilities": [],
        "provides": provides or [],
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _write_dependent(root: Path, plugin_id: str, kind: str, required: str) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "class Dependent:\n"
        "    def capabilities(self):\n"
        f"        return {{\"{kind}\": self}}\n"
        "\n"
        "def create_plugin(plugin_id, context):\n"
        f"    cap = context.get_capability(\"{required}\")\n"
        "    cap.ping()\n"
        "    return Dependent()\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [{"kind": kind, "id": "default", "path": "plugin.py", "callable": "create_plugin"}],
        "permissions": {"filesystem": "read", "gpu": False, "raw_input": False, "network": False},
        "required_capabilities": [required],
        "compat": {"requires_kernel": ">=0.0.0", "requires_schema_versions": [1]},
        "depends_on": [],
        "hash_lock": {"manifest_sha256": "", "artifact_sha256": ""},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class PluginDependencyOrderTests(unittest.TestCase):
    def test_required_capability_loads_provider_first(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            provider_id = "test.runtime.governor"
            dependent_id = "test.runtime.scheduler"
            _write_provider(root, provider_id, "cap.runtime.governor")
            _write_dependent(root, dependent_id, "cap.runtime.scheduler", "cap.runtime.governor")

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [provider_id, dependent_id]
            plugins["enabled"] = {provider_id: True, dependent_id: True}
            plugins["default_pack"] = [provider_id, dependent_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            plugins["filesystem_defaults"] = {"read": [], "readwrite": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"

            registry = PluginRegistry(config, safe_mode=False)
            loaded, _caps = registry.load_plugins()
            self.assertEqual([plugin.plugin_id for plugin in loaded], [provider_id, dependent_id])

    def test_required_capability_uses_provides_hint(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            provider_id = "test.storage.provider"
            dependent_id = "test.anchor.consumer"
            _write_provider(
                root,
                provider_id,
                "storage.metadata_store",
                provides=["storage.keyring"],
            )
            _write_dependent(root, dependent_id, "anchor.writer", "storage.keyring")

            config = _default_config()
            plugins = config.setdefault("plugins", {})
            plugins["allowlist"] = [provider_id, dependent_id]
            plugins["enabled"] = {provider_id: True, dependent_id: True}
            plugins["default_pack"] = [provider_id, dependent_id]
            plugins["search_paths"] = [str(root)]
            plugins.setdefault("locks", {})["enforce"] = False
            plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
            plugins["filesystem_defaults"] = {"read": [], "readwrite": []}
            hosting = plugins.setdefault("hosting", {})
            hosting["mode"] = "subprocess"

            registry = PluginRegistry(config, safe_mode=False)
            loaded, _caps = registry.load_plugins()
            self.assertEqual([plugin.plugin_id for plugin in loaded], [provider_id, dependent_id])


if __name__ == "__main__":
    unittest.main()
