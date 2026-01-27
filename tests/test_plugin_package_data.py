import importlib.resources as resources
import unittest


def _walk(trav):
    if trav.is_dir():
        for child in trav.iterdir():
            yield from _walk(child)
    else:
        yield trav


class PluginPackageDataTests(unittest.TestCase):
    def test_builtin_plugin_manifests_available(self) -> None:
        root = resources.files("plugins").joinpath("builtin")
        manifests = [item for item in _walk(root) if item.name == "plugin.json"]
        self.assertTrue(manifests, "No builtin plugin manifests found in package data")


if __name__ == "__main__":
    unittest.main()
