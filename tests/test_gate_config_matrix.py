from __future__ import annotations

import unittest

from tools import gate_config_matrix as mod


def _default_cfg() -> dict:
    return {
        "promptops": {
            "enabled": True,
            "require_citations": True,
            "require_query_path": True,
            "query_strategy": "normalize_query",
            "examples_path": "data/promptops/examples.json",
            "optimizer": {
                "enabled": True,
                "interval_s": 300,
                "strategies": ["normalize_query"],
                "refresh_examples": True,
            },
            "review": {
                "base_url": "http://127.0.0.1:8000/v1",
                "model": "internvl3_5_8b",
            },
        },
        "research": {"enabled": False, "owner": "hypervisor"},
        "plugins": {"enabled": {"builtin.research.default": False}},
    }


class GateConfigMatrixTests(unittest.TestCase):
    def test_validate_config_matrix_pass(self) -> None:
        checks = mod.validate_config_matrix(_default_cfg(), {"plugins": {"safe_mode": True}})
        self.assertTrue(all(bool(item.get("ok", False)) for item in checks))

    def test_validate_config_matrix_rejects_bad_review_url(self) -> None:
        cfg = _default_cfg()
        cfg["promptops"]["review"]["base_url"] = "https://example.com/v1"
        checks = mod.validate_config_matrix(cfg, {"plugins": {"safe_mode": True}})
        failed = {str(item.get("name") or "") for item in checks if not bool(item.get("ok", False))}
        self.assertIn("promptops_review_base_url_local_v1", failed)

    def test_validate_config_matrix_rejects_research_enabled(self) -> None:
        cfg = _default_cfg()
        cfg["research"]["enabled"] = True
        checks = mod.validate_config_matrix(cfg, {"plugins": {"safe_mode": True}})
        failed = {str(item.get("name") or "") for item in checks if not bool(item.get("ok", False))}
        self.assertIn("research_disabled_in_prime", failed)


if __name__ == "__main__":
    unittest.main()
