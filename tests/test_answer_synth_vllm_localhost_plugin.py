from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.answer_synth_vllm_localhost.plugin import VllmAnswerSynthesizer


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def chat_completions(self, req: dict) -> dict:
        self.requests.append(dict(req))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "claims": [
                                    {
                                        "text": "Detected relevant fact.",
                                        "evidence": [{"record_id": "rid.1", "quote": "event starts at 9:00 AM"}],
                                    }
                                ]
                            },
                            sort_keys=True,
                        )
                    }
                }
            ]
        }


class AnswerSynthVllmLocalhostPluginTests(unittest.TestCase):
    def test_injects_query_context_before_and_after_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.txt"
            pre_path = Path(tmp) / "pre.txt"
            post_path = Path(tmp) / "post.txt"
            system_path.write_text("System contract from file.", encoding="utf-8")
            pre_path.write_text("PRE_CONTEXT", encoding="utf-8")
            post_path.write_text("POST_CONTEXT", encoding="utf-8")
            fake = _FakeClient()
            cfg = {
                "model": "internvl3_5_8b",
                "promptops": {"enabled": False},
                "system_prompt_path": str(system_path),
                "query_context_pre_path": str(pre_path),
                "query_context_post_path": str(post_path),
            }
            ctx = PluginContext(config=cfg, get_capability=lambda _name: None, logger=lambda _msg, _payload=None: None)
            plugin = VllmAnswerSynthesizer("builtin.answer.synth_vllm_localhost", ctx)
            with patch("plugins.builtin.answer_synth_vllm_localhost.plugin.OpenAICompatClient", return_value=fake):
                out = plugin.synthesize(
                    "What time is the game?",
                    [{"record_id": "rid.1", "text": "event starts at 9:00 AM"}],
                )
            self.assertIn("claims", out)
            self.assertEqual(len(fake.requests), 1)
            req = fake.requests[0]
            messages = req.get("messages", [])
            self.assertEqual(str(messages[0].get("role") or ""), "system")
            self.assertEqual(str(messages[0].get("content") or ""), "System contract from file.")
            user_text = str(messages[1].get("content") or "")
            pre_idx = user_text.find("PRE_CONTEXT")
            query_idx = user_text.find("What time is the game?")
            post_idx = user_text.find("POST_CONTEXT")
            self.assertGreaterEqual(pre_idx, 0)
            self.assertGreater(query_idx, pre_idx)
            self.assertGreater(post_idx, query_idx)

    def test_missing_prompt_files_fall_back_to_builtin_prompts(self) -> None:
        fake = _FakeClient()
        cfg = {
            "model": "internvl3_5_8b",
            "promptops": {"enabled": False},
            "system_prompt_path": "missing/system.txt",
            "query_context_pre_path": "missing/pre.txt",
            "query_context_post_path": "missing/post.txt",
        }
        ctx = PluginContext(config=cfg, get_capability=lambda _name: None, logger=lambda _msg, _payload=None: None)
        plugin = VllmAnswerSynthesizer("builtin.answer.synth_vllm_localhost", ctx)
        with patch("plugins.builtin.answer_synth_vllm_localhost.plugin.OpenAICompatClient", return_value=fake):
            _ = plugin.synthesize(
                "What changed?",
                [{"record_id": "rid.2", "text": "window title changed"}],
            )
        self.assertEqual(len(fake.requests), 1)
        req = fake.requests[0]
        messages = req.get("messages", [])
        self.assertTrue(str(messages[0].get("content") or "").startswith("You are a careful assistant"))
        user_text = str(messages[1].get("content") or "")
        self.assertIn("Use the user question exactly as written below", user_text)
        self.assertIn("What changed?", user_text)
        self.assertIn("After reading the question, answer only from cited evidence snippets", user_text)


if __name__ == "__main__":
    unittest.main()
