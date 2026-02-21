from __future__ import annotations

import unittest

from tools import gate_promptops_policy as mod


def _sample_config() -> dict:
    return {
        "plugins": {
            "allowlist": list(mod.REQUIRED_PLUGIN_IDS),
            "enabled": {pid: True for pid in mod.REQUIRED_PLUGIN_IDS},
        },
        "promptops": {
            "enabled": True,
            "require_citations": True,
            "examples_path": "data/promptops/examples.json",
            "query_strategy": "normalize_query",
            "model_strategy": "model_contract",
            "persist_query_prompts": True,
            "require_query_path": True,
            "optimizer": {
                "enabled": True,
                "interval_s": 300,
                "strategies": ["normalize_query"],
                "refresh_examples": True,
            },
            "review": {"base_url": "http://127.0.0.1:8000", "require_preflight": True},
        },
    }


class GatePromptOpsPolicyTests(unittest.TestCase):
    def test_validate_promptops_policy_pass(self) -> None:
        config = _sample_config()
        lock_payload = {"plugins": {pid: {"artifact_sha256": "x"} for pid in mod.REQUIRED_PLUGIN_IDS}}
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_promptops_policy(config, lock_payload, safe_cfg)
        self.assertTrue(all(bool(item.get("ok", False)) for item in checks))

    def test_validate_promptops_policy_rejects_non_localhost_review(self) -> None:
        config = _sample_config()
        config["promptops"]["review"]["base_url"] = "https://example.com"
        lock_payload = {"plugins": {pid: {"artifact_sha256": "x"} for pid in mod.REQUIRED_PLUGIN_IDS}}
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_promptops_policy(config, lock_payload, safe_cfg)
        failed = {item["name"] for item in checks if not bool(item.get("ok", False))}
        self.assertIn("review_base_url_localhost", failed)


if __name__ == "__main__":
    unittest.main()
