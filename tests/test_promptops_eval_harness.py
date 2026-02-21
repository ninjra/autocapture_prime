import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from autocapture.promptops.harness import TemplateEvalCase, run_template_eval
from autocapture.promptops.sources import snapshot_sources


def _hash_prompt(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_sources(sources: list[dict]) -> str:
    payload = json.dumps(sources, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _config(tmp_dir: Path) -> dict:
    base = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
    base["storage"]["data_dir"] = str(tmp_dir)
    base.setdefault("paths", {})["data_dir"] = str(tmp_dir)
    promptops = base.get("promptops", {})
    promptops["history"]["enabled"] = False
    promptops["github"]["enabled"] = False
    promptops["persist_prompts"] = False
    promptops["mode"] = "auto_apply"
    promptops["strategy"] = "none"
    promptops["query_strategy"] = "none"
    return base


class PromptOpsEvalHarnessTests(unittest.TestCase):
    def test_template_eval_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            prompt = "Hello [citation]"
            sources = [{"text": "alpha"}]
            snapshot = snapshot_sources(sources)
            expected_sources_hash = _hash_sources(snapshot["sources"])
            expected_prompt_hash = _hash_prompt(prompt)
            case = TemplateEvalCase(
                case_id="case-1",
                prompt_id="query",
                prompt=prompt,
                sources=sources,
                expected={
                    "prompt_sha256": expected_prompt_hash,
                    "sources_sha256": expected_sources_hash,
                    "required_tokens": ["hello"],
                    "applied": True,
                },
            )
            report = run_template_eval(config, [case], include_prompt=True, include_sources=True)
            self.assertEqual(report["summary"]["failed"], 0)
            self.assertEqual(report["summary"]["total"], 1)
            result = report["cases"][0]
            self.assertTrue(result["ok"])
            self.assertEqual(result["prompt_sha256"], expected_prompt_hash)
            self.assertEqual(result["sources_sha256"], expected_sources_hash)

    def test_template_eval_fail_on_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(Path(tmp))
            case = TemplateEvalCase(
                case_id="case-2",
                prompt_id="query",
                prompt="Hello",
                expected={"required_tokens": ["missing"]},
            )
            report = run_template_eval(config, [case])
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertFalse(report["cases"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
