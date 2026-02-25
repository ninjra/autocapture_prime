from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import gate_promptops_policy as mod


def _sample_config() -> dict:
    return {
        "plugins": {
            "allowlist": list(mod.REQUIRED_PLUGIN_IDS),
            "enabled": {pid: True for pid in mod.REQUIRED_PLUGIN_IDS},
            "settings": {
                "builtin.answer.synth_vllm_localhost": {
                    "system_prompt_path": "promptops/prompts/answer_synth_system.txt",
                    "query_context_pre_path": "promptops/prompts/answer_synth_query_pre.txt",
                    "query_context_post_path": "promptops/prompts/answer_synth_query_post.txt",
                }
            },
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

    def test_validate_promptops_policy_allows_non8000_mode_with_ui_vlm_disabled(self) -> None:
        config = _sample_config()
        config.setdefault("plugins", {}).setdefault("enabled", {})["builtin.processing.sst.ui_vlm"] = False
        config["plugins"]["enabled"]["builtin.vlm.vllm_localhost"] = False
        config["processing"] = {
            "idle": {"extractors": {"vlm": False}},
            "sst": {"ui_vlm": {"enabled": False}},
        }
        lock_payload = {"plugins": {pid: {"artifact_sha256": "x"} for pid in mod.REQUIRED_PLUGIN_IDS}}
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_promptops_policy(config, lock_payload, safe_cfg)
        self.assertTrue(all(bool(item.get("ok", False)) for item in checks))

    def test_validate_promptops_policy_rejects_missing_prompt_path_settings(self) -> None:
        config = _sample_config()
        config["plugins"]["settings"]["builtin.answer.synth_vllm_localhost"]["query_context_post_path"] = ""
        lock_payload = {"plugins": {pid: {"artifact_sha256": "x"} for pid in mod.REQUIRED_PLUGIN_IDS}}
        safe_cfg = {"plugins": {"safe_mode": True}}
        checks = mod.validate_promptops_policy(config, lock_payload, safe_cfg)
        failed = {item["name"] for item in checks if not bool(item.get("ok", False))}
        self.assertIn("answer_synth_query_context_post_path_set", failed)

    def test_validate_promptops_policy_checks_prompt_files_when_repo_root_provided(self) -> None:
        config = _sample_config()
        lock_payload = {"plugins": {pid: {"artifact_sha256": "x"} for pid in mod.REQUIRED_PLUGIN_IDS}}
        safe_cfg = {"plugins": {"safe_mode": True}}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "promptops" / "prompts").mkdir(parents=True, exist_ok=True)
            (root / "promptops" / "prompts" / "answer_synth_system.txt").write_text("sys", encoding="utf-8")
            (root / "promptops" / "prompts" / "answer_synth_query_pre.txt").write_text("pre", encoding="utf-8")
            (root / "promptops" / "prompts" / "answer_synth_query_post.txt").write_text("", encoding="utf-8")
            checks = mod.validate_promptops_policy(config, lock_payload, safe_cfg, repo_root=root)
            failed = {item["name"] for item in checks if not bool(item.get("ok", False))}
            self.assertIn("answer_synth_query_context_post_file_exists", failed)


if __name__ == "__main__":
    unittest.main()
