from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture.promptops.optimizer import PromptOpsOptimizer


def _config(tmp: str) -> dict:
    data_dir = Path(tmp) / "data"
    prompt_dir = Path(tmp) / "promptops" / "prompts"
    metrics_path = data_dir / "promptops" / "metrics.jsonl"
    return {
        "paths": {"data_dir": str(data_dir)},
        "storage": {"data_dir": str(data_dir)},
        "plugins": {"safe_mode": True, "allowlist": [], "enabled": {}, "default_pack": [], "search_paths": []},
        "promptops": {
            "enabled": True,
            "mode": "auto_apply",
            "strategy": "append_sources",
            "query_strategy": "normalize_query",
            "max_chars": 8000,
            "max_tokens": 2000,
            "min_pass_rate_pct": 100,
            "require_citations": False,
            "model_strategy": "model_contract",
            "persist_prompts": False,
            "persist_query_prompts": True,
            "require_query_path": True,
            "sources": [],
            "examples": {
                "query.default": [{"required_tokens": ["please"], "requires_citation": False}],
            },
            "examples_path": str(data_dir / "promptops" / "examples.json"),
            "eval": {"enabled": False, "cases_path": "", "output_path": "", "include_prompt": False, "include_sources": False, "overrides": {}},
            "history": {"enabled": False, "include_prompt": False},
            "metrics": {"enabled": True, "output_path": str(metrics_path)},
            "review": {
                "base_url": "http://127.0.0.1:8000/v1",
                "enabled": False,
                "max_tokens": 64,
                "model": "internvl3_5_8b",
                "on_failure_only": True,
                "persist_prompts": False,
                "timeout_s": 5.0,
                "auto_approve": True,
                "approved_prompt_ids": [],
            },
            "github": {"enabled": False, "title": "", "body": "", "output_path": ""},
            "bundle_name": "default",
            "banned_patterns": [],
            "prompt_dir": str(prompt_dir),
            "optimizer": {
                "enabled": True,
                "interval_s": 1,
                "estimate_ms": 500,
                "metrics_window_rows": 200,
                "refresh_examples": True,
                "query_trace_path": str(data_dir / "facts" / "query_trace.ndjson"),
                "min_interactions": 3,
                "min_success_rate": 0.7,
                "max_latency_p95_ms": 4000.0,
                "max_prompt_ids": 2,
                "strategies": ["normalize_query", "model_contract"],
                "auto_promote": False,
                "min_pass_rate_delta": 0.05,
                "output_path": str(Path(tmp) / "optimizer_latest.json"),
            },
        },
    }


def _append_metric(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


class PromptOpsOptimizerTests(unittest.TestCase):
    def test_due_respects_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            optimizer = PromptOpsOptimizer(cfg)
            self.assertTrue(optimizer.due(now_monotonic=100.0))
            _ = optimizer.run_once(user_active=False, idle_seconds=60.0, force=True)
            anchor = float(optimizer._last_run_monotonic or 0.0)  # noqa: SLF001
            self.assertFalse(optimizer.due(now_monotonic=anchor + 0.2))
            self.assertTrue(optimizer.due(now_monotonic=anchor + 2.0))

    def test_relative_paths_resolve_to_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            cfg["promptops"]["metrics"]["output_path"] = "promptops/metrics.jsonl"
            cfg["promptops"]["examples_path"] = "promptops/examples.json"
            cfg["promptops"]["optimizer"]["query_trace_path"] = "facts/query_trace.ndjson"
            cfg["promptops"]["optimizer"]["output_path"] = "artifacts/promptops/optimizer_latest.json"
            optimizer = PromptOpsOptimizer(cfg)
            data_root = Path(cfg["paths"]["data_dir"])
            self.assertEqual(optimizer._metrics_path(), data_root / "promptops" / "metrics.jsonl")  # noqa: SLF001
            self.assertEqual(optimizer._examples_path(), data_root / "promptops" / "examples.json")  # noqa: SLF001
            self.assertEqual(optimizer._trace_path(), data_root / "facts" / "query_trace.ndjson")  # noqa: SLF001
            self.assertEqual(optimizer._report_path(), data_root / "artifacts" / "promptops" / "optimizer_latest.json")  # noqa: SLF001

    def test_relative_paths_use_env_data_root_override(self) -> None:
        with tempfile.TemporaryDirectory() as cfg_tmp, tempfile.TemporaryDirectory() as env_tmp:
            cfg = _config(cfg_tmp)
            cfg["paths"]["data_dir"] = "data"
            cfg["storage"]["data_dir"] = "data"
            cfg["promptops"]["metrics"]["output_path"] = "promptops/metrics.jsonl"
            cfg["promptops"]["examples_path"] = "promptops/examples.json"
            cfg["promptops"]["optimizer"]["query_trace_path"] = "facts/query_trace.ndjson"
            cfg["promptops"]["optimizer"]["output_path"] = "artifacts/promptops/optimizer_latest.json"
            with mock.patch.dict("os.environ", {"AUTOCAPTURE_DATA_DIR": env_tmp}, clear=False):
                optimizer = PromptOpsOptimizer(cfg)
                data_root = Path(env_tmp)
                self.assertEqual(optimizer._metrics_path(), data_root / "promptops" / "metrics.jsonl")  # noqa: SLF001
                self.assertEqual(optimizer._examples_path(), data_root / "promptops" / "examples.json")  # noqa: SLF001
                self.assertEqual(optimizer._trace_path(), data_root / "facts" / "query_trace.ndjson")  # noqa: SLF001
                self.assertEqual(optimizer._report_path(), data_root / "artifacts" / "promptops" / "optimizer_latest.json")  # noqa: SLF001

    def test_skips_when_user_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            optimizer = PromptOpsOptimizer(cfg)
            report = optimizer.run_once(user_active=True, idle_seconds=0.2, force=False)
            self.assertTrue(bool(report.get("skipped")))
            self.assertEqual(str(report.get("skip_reason")), "user_active")

    def test_generates_candidates_for_weak_prompt_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            prompt_dir = Path(cfg["promptops"]["prompt_dir"])
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / "query_default.txt").write_text("pls help w/ this", encoding="utf-8")
            metrics_path = Path(cfg["promptops"]["metrics"]["output_path"])
            for idx in range(4):
                _append_metric(
                    metrics_path,
                    {
                        "type": "promptops.model_interaction",
                        "prompt_id": "query.default",
                        "success": bool(idx == 0),
                        "latency_ms": 2500.0 + float(idx * 10),
                    },
                )
            optimizer = PromptOpsOptimizer(cfg)
            report = optimizer.run_once(user_active=False, idle_seconds=80.0, force=True)
            self.assertFalse(bool(report.get("skipped")))
            self.assertTrue(bool(report.get("examples_refreshed", False)))
            self.assertTrue(Path(str(report.get("examples_path") or "")).exists())
            weak = report.get("weak_prompt_ids", [])
            self.assertTrue(isinstance(weak, list) and weak)
            candidates = report.get("candidates", [])
            self.assertTrue(isinstance(candidates, list) and candidates)
            first = candidates[0]
            self.assertEqual(first.get("prompt_id"), "query.default")
            self.assertEqual(first.get("status"), "ok")

    def test_optimizer_uses_examples_path_when_inline_examples_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            cfg["promptops"]["examples"] = {}
            cfg["promptops"]["optimizer"]["refresh_examples"] = False
            examples_path = Path(cfg["promptops"]["examples_path"])
            examples_path.parent.mkdir(parents=True, exist_ok=True)
            examples_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "promptops_examples": {
                            "query.default": [{"required_tokens": ["help"], "requires_citation": False}]
                        },
                    }
                ),
                encoding="utf-8",
            )
            prompt_dir = Path(cfg["promptops"]["prompt_dir"])
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / "query_default.txt").write_text("pls help w/ this", encoding="utf-8")
            metrics_path = Path(cfg["promptops"]["metrics"]["output_path"])
            for idx in range(4):
                _append_metric(
                    metrics_path,
                    {
                        "type": "promptops.model_interaction",
                        "prompt_id": "query.default",
                        "success": bool(idx == 0),
                        "latency_ms": 2500.0 + float(idx * 10),
                    },
                )
            optimizer = PromptOpsOptimizer(cfg)
            report = optimizer.run_once(user_active=False, idle_seconds=90.0, force=True)
            candidates = report.get("candidates", [])
            self.assertTrue(candidates)
            self.assertGreater(int(candidates[0].get("evaluation_total", 0) or 0), 0)

    def test_optimizer_bootstraps_prompt_from_metrics_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            cfg["promptops"]["examples"] = {
                "hard_vlm.adv_incident": [{"required_tokens": ["policy"], "requires_citation": False}]
            }
            metrics_path = Path(cfg["promptops"]["metrics"]["output_path"])
            for idx in range(4):
                _append_metric(
                    metrics_path,
                    {
                        "type": "promptops.model_interaction",
                        "prompt_id": "hard_vlm.adv_incident",
                        "success": bool(idx == 0),
                        "latency_ms": 5000.0 + float(idx * 5),
                        "prompt_effective_text": "Answer with policy and cite evidence.",
                    },
                )
            optimizer = PromptOpsOptimizer(cfg)
            report = optimizer.run_once(user_active=False, idle_seconds=120.0, force=True)
            candidates = report.get("candidates", [])
            target = [row for row in candidates if row.get("prompt_id") == "hard_vlm.adv_incident"]
            self.assertTrue(target)
            first = target[0]
            self.assertNotEqual(first.get("reason"), "prompt_not_found")
            self.assertTrue(bool(first.get("bootstrapped_prompt", False)))

    def test_optimizer_uses_fallback_prompt_for_missing_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _config(tmp)
            cfg["promptops"]["examples"] = {
                "hard_vlm.adv_incident": [{"required_tokens": ["policy"], "requires_citation": False}]
            }
            metrics_path = Path(cfg["promptops"]["metrics"]["output_path"])
            for idx in range(4):
                _append_metric(
                    metrics_path,
                    {
                        "type": "promptops.model_interaction",
                        "prompt_id": "hard_vlm.adv_incident",
                        "success": bool(idx == 0),
                        "latency_ms": 4500.0 + float(idx * 10),
                    },
                )
            optimizer = PromptOpsOptimizer(cfg)
            report = optimizer.run_once(user_active=False, idle_seconds=120.0, force=True)
            candidates = report.get("candidates", [])
            target = [row for row in candidates if row.get("prompt_id") == "hard_vlm.adv_incident"]
            self.assertTrue(target)
            self.assertNotEqual(target[0].get("reason"), "prompt_not_found")


if __name__ == "__main__":
    unittest.main()
