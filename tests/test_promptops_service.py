import copy
import tempfile
import unittest

from autocapture.promptops.service import PromptOpsService, get_promptops_layer


def _base_config(tmp: str) -> dict:
    return {
        "paths": {"data_dir": tmp},
        "storage": {"data_dir": tmp},
        "plugins": {"safe_mode": True, "allowlist": [], "enabled": {}, "default_pack": [], "search_paths": []},
        "promptops": {
            "bundle_name": "missing",
            "enabled": True,
            "history": {"enabled": False},
            "github": {"enabled": False},
            "metrics": {"enabled": False},
            "review": {"enabled": False},
            "sources": [],
            "strategy": "none",
            "query_strategy": "none",
        },
    }


class PromptOpsServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        PromptOpsService.clear_cache()

    def test_returns_cached_layer_for_same_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            layer_one = get_promptops_layer(config)
            layer_two = get_promptops_layer(config)
            self.assertIs(layer_one, layer_two)
            self.assertEqual(PromptOpsService.cache_size(), 1)

    def test_config_change_creates_new_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_one = _base_config(tmp)
            config_two = copy.deepcopy(config_one)
            config_two["promptops"]["query_strategy"] = "normalize_query"
            layer_one = get_promptops_layer(config_one)
            layer_two = get_promptops_layer(config_two)
            self.assertIsNot(layer_one, layer_two)
            self.assertEqual(PromptOpsService.cache_size(), 2)


if __name__ == "__main__":
    unittest.main()

