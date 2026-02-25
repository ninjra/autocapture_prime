import copy
import os
import tempfile
import unittest
from unittest import mock

from autocapture.promptops.service import PromptOpsService, get_promptops_api, get_promptops_layer


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
    def setUp(self) -> None:
        PromptOpsService.clear_cache()

    def tearDown(self) -> None:
        PromptOpsService.clear_cache()

    def test_returns_cached_layer_for_same_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            before = PromptOpsService.cache_size()
            layer_one = get_promptops_layer(config)
            layer_two = get_promptops_layer(config)
            self.assertIs(layer_one, layer_two)
            self.assertEqual(PromptOpsService.cache_size(), before + 1)

    def test_config_change_creates_new_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_one = _base_config(tmp)
            config_two = copy.deepcopy(config_one)
            config_two["promptops"]["query_strategy"] = "normalize_query"
            before = PromptOpsService.cache_size()
            layer_one = get_promptops_layer(config_one)
            layer_two = get_promptops_layer(config_two)
            self.assertIsNot(layer_one, layer_two)
            self.assertEqual(PromptOpsService.cache_size(), before + 2)

    def test_runtime_only_config_change_reuses_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_one = _base_config(tmp)
            config_two = copy.deepcopy(config_one)
            config_two["runtime"] = {"nonce": 123}
            before = PromptOpsService.cache_size()
            layer_one = get_promptops_layer(config_one)
            layer_two = get_promptops_layer(config_two)
            self.assertIs(layer_one, layer_two)
            self.assertEqual(PromptOpsService.cache_size(), before + 1)

    def test_returns_cached_api_for_same_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            api_one = get_promptops_api(config)
            api_two = get_promptops_api(config)
            self.assertIs(api_one, api_two)

    def test_service_cache_is_bounded_for_unique_configs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AUTOCAPTURE_PROMPTOPS_SERVICE_CACHE_MAX_ENTRIES": "4"}, clear=False):
                first_api = None
                configs: list[dict] = []
                for i in range(12):
                    cfg = _base_config(tmp)
                    cfg["promptops"]["query_strategy"] = f"strategy_{i}"
                    configs.append(cfg)
                    api = get_promptops_api(cfg)
                    if i == 0:
                        first_api = api
                self.assertIsNotNone(first_api)
                self.assertLessEqual(PromptOpsService.cache_size(), 4)
                self.assertLessEqual(len(PromptOpsService._apis), 4)  # noqa: SLF001
                recached_first = get_promptops_api(configs[0])
                self.assertIsNot(recached_first, first_api)
                self.assertLessEqual(PromptOpsService.cache_size(), 4)
                self.assertLessEqual(len(PromptOpsService._apis), 4)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
