import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.plugin_system.registry import PluginRegistry


def _load_default_config() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _write_plugin(root: Path, plugin_id: str, *, conflicts_with: list[str] | None = None) -> None:
    plugin_dir = root / plugin_id.replace(".", "_")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "def create_plugin(plugin_id, context):\n"
        "    class P:\n"
        "        def capabilities(self):\n"
        "            return {}\n"
        "    return P()\n",
        encoding="utf-8",
    )
    manifest = {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "enabled": True,
        "entrypoints": [
            {
                "kind": "plugin",
                "id": "main",
                "path": "plugin.py",
                "callable": "create_plugin",
            }
        ],
        "permissions": {
            "filesystem": "none",
            "gpu": False,
            "raw_input": False,
            "network": False,
        },
        "compat": {
            "requires_kernel": ">=0.0.0",
            "requires_schema_versions": [1],
        },
        "depends_on": [],
        "conflicts_with": conflicts_with or [],
        "hash_lock": {
            "manifest_sha256": "",
            "artifact_sha256": "",
        },
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class PluginConflictTests(unittest.TestCase):
    def _base_config(self, search_path: Path) -> dict:
        config = _load_default_config()
        plugins = config.setdefault("plugins", {})
        plugins["allowlist"] = ["test.conflict.a", "test.conflict.b"]
        plugins["enabled"] = {"test.conflict.a": True, "test.conflict.b": True}
        plugins["default_pack"] = ["test.conflict.a", "test.conflict.b"]
        plugins["search_paths"] = [str(search_path)]
        plugins.setdefault("locks", {})["enforce"] = False
        hosting = plugins.setdefault("hosting", {})
        hosting["mode"] = "inproc"
        hosting["inproc_allowlist"] = ["test.conflict.a", "test.conflict.b"]
        plugins["conflicts"] = {"enforce": True, "allow_pairs": []}
        return config

    def test_conflict_blocks_load(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            _write_plugin(root, "test.conflict.a", conflicts_with=["test.conflict.b"])
            _write_plugin(root, "test.conflict.b")
            config = self._base_config(root)
            registry = PluginRegistry(config, safe_mode=False)
            with self.assertRaises(PluginError):
                registry.load_plugins()

    def test_conflict_allow_pair_permits_load(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            _write_plugin(root, "test.conflict.a", conflicts_with=["test.conflict.b"])
            _write_plugin(root, "test.conflict.b")
            config = self._base_config(root)
            # Allow the pair in reversed order to exercise normalization.
            config["plugins"]["conflicts"]["allow_pairs"] = [["test.conflict.b", "test.conflict.a"]]
            registry = PluginRegistry(config, safe_mode=False)
            loaded, _caps = registry.load_plugins()
            loaded_ids = sorted(plugin.plugin_id for plugin in loaded)
            self.assertEqual(loaded_ids, ["test.conflict.a", "test.conflict.b"])


if __name__ == "__main__":
    unittest.main()
