import tempfile
import textwrap
import unittest
from pathlib import Path

from autocapture.plugins.manager import PluginManager


class PluginDiscoveryNoImportTests(unittest.TestCase):
    def test_discovery_does_not_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "mx.test.yaml"
            manifest.write_text(
                textwrap.dedent(
                    """
                    schema_version: 1
                    plugin_id: mx.test
                    version: 0.1.0
                    display_name: Test Plugin
                    description: Test
                    extensions:
                      - kind: test.kind
                        factory: nonexistent.module:create
                        name: default
                        version: 0.1.0
                        caps: []
                        pillars: {}
                    """
                ).strip(),
                encoding="utf-8",
            )
            config = {
                "plugins": {
                    "search_paths": [str(root)],
                    "allowlist": ["mx.test"],
                    "enabled": {"mx.test": True},
                    "default_pack": ["mx.test"],
                }
            }
            manager = PluginManager(config, safe_mode=False)
            plugins = manager.list_plugins()
            plugin_ids = {p["plugin_id"] for p in plugins}
            self.assertIn("mx.test", plugin_ids)


if __name__ == "__main__":
    unittest.main()
