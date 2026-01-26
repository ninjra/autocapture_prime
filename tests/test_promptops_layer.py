import tempfile
import unittest

from autocapture.promptops.engine import PromptOpsLayer


def _base_config(tmp: str) -> dict:
    return {
        "paths": {"data_dir": tmp},
        "storage": {"data_dir": tmp},
        "plugins": {"safe_mode": True, "allowlist": [], "enabled": {}, "default_pack": [], "search_paths": []},
        "promptops": {
            "banned_patterns": [],
            "bundle_name": "missing",
            "enabled": True,
            "examples": {},
            "github": {"enabled": False, "title": "", "body": "", "output_path": "artifacts/promptops_pr.json"},
            "history": {"enabled": False, "include_prompt": False},
            "max_chars": 8000,
            "max_tokens": 2000,
            "min_pass_rate_pct": 100,
            "mode": "auto_apply",
            "persist_prompts": False,
            "query_strategy": "none",
            "require_citations": False,
            "sources": [],
            "strategy": "append_sources",
        },
    }


class PromptOpsLayerTests(unittest.TestCase):
    def test_prepare_prompt_appends_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            layer = PromptOpsLayer(config)
            result = layer.prepare_prompt("Hello", prompt_id="test", sources=[{"text": "alpha", "id": "src1"}])
            self.assertIn("# Sources", result.prompt)
            self.assertTrue(result.applied)

    def test_prepare_prompt_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["promptops"]["enabled"] = False
            layer = PromptOpsLayer(config)
            result = layer.prepare_prompt("Hello", prompt_id="test")
            self.assertEqual(result.prompt, "Hello")
            self.assertFalse(result.applied)


if __name__ == "__main__":
    unittest.main()
