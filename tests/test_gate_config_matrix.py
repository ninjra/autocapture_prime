from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


def _load_module():
    path = pathlib.Path("tools/gate_config_matrix.py")
    spec = importlib.util.spec_from_file_location("gate_config_matrix_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _find_check(checks: list[dict[str, object]], name: str) -> dict[str, object]:
    for item in checks:
        if str(item.get("name", "")) == name:
            return item
    raise AssertionError(f"missing check: {name}")


class GateConfigMatrixTests(unittest.TestCase):
    def test_non8000_profile_passes_contract_checks(self) -> None:
        mod = _load_module()
        enabled = {pid: True for pid in mod.NON8000_DEFAULT_REQUIRED_PLUGIN_IDS}
        enabled.update({pid: False for pid in mod.CAPTURE_DEPRECATED_PLUGIN_IDS})
        enabled.update({pid: False for pid in mod.REQUIRES_8000_PLUGIN_IDS})
        default_cfg = {
            "promptops": {
                "enabled": True,
                "require_citations": True,
                "examples_path": "data/promptops/examples.json",
                "require_query_path": True,
                "query_strategy": "hybrid",
                "review": {"base_url": "http://127.0.0.1/v1", "model": mod.EXTERNAL_VLLM_EXPECTED_MODEL},
                "optimizer": {
                    "enabled": True,
                    "interval_s": 60,
                    "strategies": ["baseline"],
                    "refresh_examples": True,
                },
            },
            "research": {"enabled": False, "owner": "hypervisor"},
            "plugins": {"enabled": enabled, "allowlist": list(mod.NON8000_DEFAULT_REQUIRED_PLUGIN_IDS)},
            "processing": {
                "idle": {"extractors": {"vlm": False}},
                "sst": {"ui_vlm": {"enabled": False}},
            },
        }
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_config_matrix(default_cfg, safe_cfg)
        self.assertTrue(bool(_find_check(checks, "capture_plugins_deprecated").get("ok", False)))
        self.assertTrue(bool(_find_check(checks, "non8000_required_plugins_enabled").get("ok", False)))
        self.assertTrue(bool(_find_check(checks, "non8000_required_plugins_allowlisted").get("ok", False)))
        self.assertTrue(bool(_find_check(checks, "requires_8000_plugins_disabled").get("ok", False)))
        self.assertTrue(bool(_find_check(checks, "idle_vlm_extractor_disabled_non8000").get("ok", False)))
        self.assertTrue(bool(_find_check(checks, "sst_ui_vlm_disabled_non8000").get("ok", False)))

    def test_capture_plugin_enabled_fails_contract(self) -> None:
        mod = _load_module()
        enabled = {pid: True for pid in mod.NON8000_DEFAULT_REQUIRED_PLUGIN_IDS}
        enabled.update({pid: False for pid in mod.REQUIRES_8000_PLUGIN_IDS})
        enabled["builtin.capture.basic"] = True
        default_cfg = {
            "promptops": {"review": {"base_url": "http://127.0.0.1/v1", "model": mod.EXTERNAL_VLLM_EXPECTED_MODEL}},
            "research": {"enabled": False, "owner": "hypervisor"},
            "plugins": {"enabled": enabled},
            "processing": {"idle": {"extractors": {"vlm": False}}, "sst": {"ui_vlm": {"enabled": False}}},
        }
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_config_matrix(default_cfg, safe_cfg)
        self.assertFalse(bool(_find_check(checks, "capture_plugins_deprecated").get("ok", True)))

    def test_requires_8000_plugin_enabled_fails_contract(self) -> None:
        mod = _load_module()
        enabled = {pid: True for pid in mod.NON8000_DEFAULT_REQUIRED_PLUGIN_IDS}
        enabled.update({pid: False for pid in mod.CAPTURE_DEPRECATED_PLUGIN_IDS})
        enabled["builtin.vlm.vllm_localhost"] = True
        default_cfg = {
            "promptops": {"review": {"base_url": "http://127.0.0.1/v1", "model": mod.EXTERNAL_VLLM_EXPECTED_MODEL}},
            "research": {"enabled": False, "owner": "hypervisor"},
            "plugins": {"enabled": enabled},
            "processing": {"idle": {"extractors": {"vlm": False}}, "sst": {"ui_vlm": {"enabled": False}}},
        }
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_config_matrix(default_cfg, safe_cfg)
        self.assertFalse(bool(_find_check(checks, "requires_8000_plugins_disabled").get("ok", True)))

    def test_non8000_required_plugin_not_allowlisted_fails_contract(self) -> None:
        mod = _load_module()
        enabled = {pid: True for pid in mod.NON8000_DEFAULT_REQUIRED_PLUGIN_IDS}
        enabled.update({pid: False for pid in mod.CAPTURE_DEPRECATED_PLUGIN_IDS})
        enabled.update({pid: False for pid in mod.REQUIRES_8000_PLUGIN_IDS})
        allowlist = [pid for pid in mod.NON8000_DEFAULT_REQUIRED_PLUGIN_IDS if pid != "builtin.state.retrieval"]
        default_cfg = {
            "promptops": {"review": {"base_url": "http://127.0.0.1/v1", "model": mod.EXTERNAL_VLLM_EXPECTED_MODEL}},
            "research": {"enabled": False, "owner": "hypervisor"},
            "plugins": {"enabled": enabled, "allowlist": allowlist},
            "processing": {"idle": {"extractors": {"vlm": False}}, "sst": {"ui_vlm": {"enabled": False}}},
        }
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_config_matrix(default_cfg, safe_cfg)
        self.assertFalse(bool(_find_check(checks, "non8000_required_plugins_allowlisted").get("ok", True)))


if __name__ == "__main__":
    unittest.main()
