import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

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
            "persist_query_prompts": False,
            "query_strategy": "none",
            "model_strategy": "model_contract",
            "require_citations": False,
            "sources": [],
            "strategy": "append_sources",
            "metrics": {
                "enabled": True,
                "output_path": "",
            },
            "review": {
                "enabled": False,
            },
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
            self.assertIsInstance(result.trace, dict)
            self.assertEqual(result.trace.get("strategy"), "append_sources")
            stages = result.trace.get("stages_ms", {})
            self.assertIsInstance(stages, dict)
            self.assertIn("snapshot", stages)
            self.assertIn("propose", stages)
            self.assertIn("validate", stages)
            self.assertIn("evaluate", stages)
            self.assertIn("total", stages)

    def test_prepare_prompt_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["promptops"]["enabled"] = False
            layer = PromptOpsLayer(config)
            result = layer.prepare_prompt("Hello", prompt_id="test")
            self.assertEqual(result.prompt, "Hello")
            self.assertFalse(result.applied)

    def test_prepare_query_normalize_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["promptops"]["query_strategy"] = "normalize_query"
            layer = PromptOpsLayer(config)
            result = layer.prepare_query("pls help w/ q", prompt_id="query")
            self.assertEqual(result.prompt, "please help with q?")

    def test_prepare_query_does_not_reuse_stored_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["promptops"]["query_strategy"] = "normalize_query"
            layer = PromptOpsLayer(config)
            layer._store.set("query", "old saved query")
            result = layer.prepare_query("pls help w/ new ask", prompt_id="query")
            self.assertEqual(result.prompt, "please help with new ask?")

    def test_record_model_interaction_writes_metrics_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            config = _base_config(tmp)
            config["promptops"]["metrics"]["output_path"] = str(metrics_path)
            layer = PromptOpsLayer(config)
            out = layer.record_model_interaction(
                prompt_id="query",
                provider_id="query.classic",
                model="",
                prompt_input="what song is playing",
                prompt_effective="what song is playing?",
                response_text="indeterminate",
                success=False,
                latency_ms=12.3,
                error="no_claims",
                metadata={"case": "unit"},
            )
            self.assertEqual(out, {"reviewed": False, "updated": False})
            lines = metrics_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row.get("type"), "promptops.model_interaction")
            self.assertEqual(row.get("prompt_id"), "query")
            self.assertEqual(row.get("provider_id"), "query.classic")
            self.assertFalse(row.get("success"))

    def test_prepare_prompt_metrics_include_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            config = _base_config(tmp)
            config["promptops"]["metrics"]["output_path"] = str(metrics_path)
            layer = PromptOpsLayer(config)
            _ = layer.prepare_prompt("hello", prompt_id="query", sources=[{"text": "alpha"}])
            lines = metrics_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertTrue(lines)
            row = json.loads(lines[-1])
            self.assertEqual(row.get("type"), "promptops.prepare_prompt")
            self.assertIn("trace", row)
            trace = row.get("trace", {})
            self.assertIsInstance(trace, dict)
            self.assertIn("stages_ms", trace)

    def test_bundle_miss_is_cached_after_first_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _base_config(tmp)
            config["promptops"]["bundle_name"] = "missing_bundle_for_test"
            layer = PromptOpsLayer(config)
            with mock.patch("autocapture.promptops.engine.PluginRegistry", side_effect=RuntimeError("no bundle")) as reg:
                _ = layer.prepare_prompt("hello", prompt_id="one")
                _ = layer.prepare_prompt("hello again", prompt_id="two")
            self.assertEqual(reg.call_count, 1)

    def test_review_requires_explicit_approval_before_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            prompt_path = Path(tmp) / "query.prompt.txt"
            config = _base_config(tmp)
            config["promptops"]["metrics"]["output_path"] = str(metrics_path)
            config["promptops"]["review"] = {
                "enabled": True,
                "on_failure_only": True,
                "persist_prompts": True,
                "auto_approve": False,
                "approved_prompt_ids": [],
                "base_url": "http://127.0.0.1:8000",
                "model": "",
                "timeout_s": 5.0,
                "max_tokens": 64,
            }
            config["promptops"]["examples"] = {
                "query": [{"required_tokens": ["hello"], "requires_citation": False}]
            }
            config["promptops"]["prompt_dir"] = str(Path(tmp))
            layer = PromptOpsLayer(config)
            with mock.patch.object(layer, "_review_with_model", return_value="hello [source]"):
                out = layer.record_model_interaction(
                    prompt_id="query",
                    provider_id="query.classic",
                    model="",
                    prompt_input="hello",
                    prompt_effective="hello",
                    response_text="",
                    success=False,
                    latency_ms=5.0,
                    error="failed",
                    metadata={"case": "approval"},
                )
            self.assertTrue(out.get("reviewed"))
            self.assertFalse(out.get("updated"))
            self.assertTrue(out.get("pending_approval"))
            self.assertFalse(prompt_path.exists())

    def test_review_no_examples_does_not_persist_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            prompt_path = Path(tmp) / "query.txt"
            config = _base_config(tmp)
            config["promptops"]["metrics"]["output_path"] = str(metrics_path)
            config["promptops"]["review"] = {
                "enabled": True,
                "on_failure_only": True,
                "persist_prompts": True,
                "auto_approve": True,
                "base_url": "http://127.0.0.1:8000",
                "model": "internvl3_5_8b",
                "timeout_s": 5.0,
                "max_tokens": 64,
                "allow_empty_examples": False,
            }
            config["promptops"]["prompt_dir"] = str(Path(tmp))
            layer = PromptOpsLayer(config)
            with mock.patch.object(layer, "_review_with_model", return_value="hello [source]"):
                out = layer.record_model_interaction(
                    prompt_id="query",
                    provider_id="query.classic",
                    model="",
                    prompt_input="hello",
                    prompt_effective="hello",
                    response_text="",
                    success=False,
                    latency_ms=5.0,
                    error="failed",
                    metadata={"case": "missing_examples"},
                )
            self.assertTrue(out.get("reviewed"))
            self.assertFalse(out.get("updated"))
            self.assertFalse(prompt_path.exists())
            rows = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            review_rows = [row for row in rows if row.get("type") == "promptops.review_result"]
            self.assertTrue(review_rows)
            self.assertEqual(int(review_rows[-1].get("evaluation_total", -1)), 0)
            self.assertFalse(bool(review_rows[-1].get("evaluation_ok", True)))

    def test_review_failure_records_reason_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            config = _base_config(tmp)
            config["promptops"]["metrics"]["output_path"] = str(metrics_path)
            config["promptops"]["review"] = {
                "enabled": True,
                "on_failure_only": True,
                "persist_prompts": True,
                "auto_approve": True,
                "base_url": "http://127.0.0.1:8000",
                "model": "internvl3_5_8b",
                "timeout_s": 5.0,
                "max_tokens": 64,
            }
            layer = PromptOpsLayer(config)
            with mock.patch.object(
                layer,
                "_review_with_model",
                return_value={"candidate": "", "error": "review_preflight_failed:models_unreachable", "meta": {"preflight": {"ok": False}}},
            ):
                out = layer.record_model_interaction(
                    prompt_id="query",
                    provider_id="query.classic",
                    model="",
                    prompt_input="hello",
                    prompt_effective="hello",
                    response_text="",
                    success=False,
                    latency_ms=5.0,
                    error="failed",
                    metadata={"case": "review_fail"},
                )
            self.assertTrue(out.get("reviewed"))
            self.assertFalse(out.get("updated"))
            rows = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            review_rows = [row for row in rows if row.get("type") == "promptops.review_result"]
            self.assertTrue(review_rows)
            self.assertIn("review_preflight_failed", str(review_rows[-1].get("review_error") or ""))


if __name__ == "__main__":
    unittest.main()
