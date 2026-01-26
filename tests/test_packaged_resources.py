import importlib.resources as resources
import unittest


class PackagedResourcesTests(unittest.TestCase):
    def test_config_and_contracts_resources_present(self) -> None:
        config_default = resources.files("config").joinpath("default.json")
        contracts_schema = resources.files("contracts").joinpath("config_schema.json")
        self.assertTrue(config_default.is_file())
        self.assertTrue(contracts_schema.is_file())

    def test_plugins_resources_present(self) -> None:
        plugin_manifest = resources.files("plugins").joinpath("builtin", "anchor_basic", "plugin.json")
        self.assertTrue(plugin_manifest.is_file())


if __name__ == "__main__":
    unittest.main()
