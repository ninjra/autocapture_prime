from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocapture.promptops.api import PromptOpsAPI


def _config(tmp: str) -> dict:
    prompt_dir = Path(tmp) / "promptops" / "prompts"
    return {
        "paths": {"data_dir": tmp},
        "storage": {"data_dir": tmp},
        "plugins": {"safe_mode": True, "allowlist": [], "enabled": {}, "default_pack": [], "search_paths": []},
        "promptops": {
            "bundle_name": "missing",
            "enabled": True,
            "history": {"enabled": False, "include_prompt": False},
            "github": {"enabled": False, "title": "", "body": "", "output_path": ""},
            "metrics": {"enabled": False, "output_path": str(Path(tmp) / "metrics.jsonl")},
            "review": {
                "enabled": False,
                "base_url": "http://127.0.0.1:8000/v1",
                "model": "internvl3_5_8b",
                "max_tokens": 128,
                "on_failure_only": True,
                "persist_prompts": False,
                "timeout_s": 10.0,
                "auto_approve": True,
                "approved_prompt_ids": [],
            },
            "sources": [],
            "strategy": "append_sources",
            "query_strategy": "normalize_query",
            "model_strategy": "model_contract",
            "mode": "auto_apply",
            "max_chars": 8000,
            "max_tokens": 2000,
            "min_pass_rate_pct": 100,
            "require_citations": False,
            "persist_prompts": False,
            "persist_query_prompts": False,
            "require_query_path": True,
            "examples": {
                "query.default": [{"required_tokens": ["please"], "requires_citation": False}],
                "llm.local": [{"required_tokens": ["Answer policy"], "requires_citation": False}],
            },
            "prompt_dir": str(prompt_dir),
            "banned_patterns": [],
            "eval": {"enabled": False, "cases_path": "", "output_path": "", "include_prompt": False, "include_sources": False, "overrides": {}},
        },
    }


class PromptOpsApiTests(unittest.TestCase):
    def test_prepare_query_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = PromptOpsAPI(_config(tmp))
            out = api.prepare("query", "pls help w/ it", {"prompt_id": "query.default"})
            self.assertEqual(out.prompt, "please help with it?")
            self.assertEqual(out.prompt_id, "query.default")
            self.assertIsInstance(out.trace, dict)

    def test_recommend_template_prefers_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            prompt_dir = Path(cfg["promptops"]["prompt_dir"])
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / "query_default.txt").write_text("stored query template", encoding="utf-8")
            api = PromptOpsAPI(cfg)
            rec = api.recommend_template("query", "hello", {"prompt_id": "query.default"})
            self.assertEqual(rec.get("source"), "stored_prompt")
            self.assertIn("stored", str(rec.get("recommended_prompt") or ""))

    def test_prepare_non_query_uses_model_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = PromptOpsAPI(_config(tmp))
            out = api.prepare("llm.local", "Respond succinctly", {"prompt_id": "llm.local", "strategy": "model_contract"})
            self.assertIn("Answer policy:", out.prompt)


if __name__ == "__main__":
    unittest.main()
