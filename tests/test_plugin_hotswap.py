import importlib
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from autocapture.plugins.manager import PluginManager


class PluginHotSwapTests(unittest.TestCase):
    def test_hotswap_reloads_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_path = root / "mx_hot.py"
            manifest_path = root / "mx.hot.yaml"
            module_path.write_text(
                "def create(plugin_id):\n    return type('P', (), {'value': 'v1'})()\n",
                encoding="utf-8",
            )
            manifest_path.write_text(
                textwrap.dedent(
                    """
                    schema_version: 1
                    plugin_id: mx.hot
                    version: 0.1.0
                    display_name: Hot
                    description: Hot swap
                    extensions:
                      - kind: hot.kind
                        factory: mx_hot:create
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
                    "allowlist": ["mx.hot"],
                    "enabled": {"mx.hot": True},
                    "default_pack": ["mx.hot"],
                }
            }
            import sys

            sys.path.insert(0, str(root))
            try:
                manager = PluginManager(config, safe_mode=False)
                inst1 = manager.get_extension("hot.kind").instance
                self.assertEqual(getattr(inst1, "value", None), "v1")

                module_path.write_text(
                    "def create(plugin_id):\n    return type('P', (), {'value': 'v2'})()\n",
                    encoding="utf-8",
                )
                time.sleep(0.01)
                manifest_path.write_text(
                    textwrap.dedent(
                        """
                        schema_version: 1
                        plugin_id: mx.hot
                        version: 0.1.1
                        display_name: Hot
                        description: Hot swap
                        extensions:
                          - kind: hot.kind
                            factory: mx_hot:create
                            name: default
                            version: 0.1.1
                            caps: []
                            pillars: {}
                        """
                    ).strip(),
                    encoding="utf-8",
                )
                manager.refresh()
                importlib.invalidate_caches()
                inst2 = manager.get_extension("hot.kind").instance
                self.assertEqual(getattr(inst2, "value", None), "v2")
            finally:
                sys.path.remove(str(root))


if __name__ == "__main__":
    unittest.main()
