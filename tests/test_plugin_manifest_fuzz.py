import json
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginError, ConfigError
from autocapture_nx.plugin_system.registry import PluginRegistry


class PluginManifestFuzzTests(unittest.TestCase):
    def test_manifest_validation_rejects_invalid_shapes(self) -> None:
        config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        registry = PluginRegistry(config, safe_mode=True)
        manifest_paths = registry.discover_manifest_paths()
        self.assertTrue(manifest_paths, "no plugin manifests found")
        manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        registry._validate_manifest(manifest)

        def _mutate(fn):
            data = json.loads(json.dumps(manifest))
            fn(data)
            with self.assertRaises((PluginError, ConfigError)):
                registry._validate_manifest(data)

        _mutate(lambda m: m.pop("plugin_id", None))
        _mutate(lambda m: m.pop("version", None))
        _mutate(lambda m: m.__setitem__("entrypoints", {}))
        _mutate(lambda m: m.__setitem__("permissions", {"filesystem": "read"}))
        _mutate(lambda m: m.__setitem__("compat", {}))
        _mutate(lambda m: m.__setitem__("hash_lock", {"manifest_sha256": ""}))
        _mutate(lambda m: m.__setitem__("required_capabilities", "not-a-list"))


if __name__ == "__main__":
    unittest.main()
