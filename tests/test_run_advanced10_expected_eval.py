from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/run_advanced10_queries.py")
    spec = importlib.util.spec_from_file_location("run_advanced10_queries_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunAdvanced10ExpectedEvalTests(unittest.TestCase):
    def test_run_query_retries_instance_lock_then_succeeds(self) -> None:
        mod = _load_module()
        with mock.patch.object(
            mod,
            "_run_query_once",
            side_effect=[
                {"ok": False, "error": "ERROR: instance_lock_held", "answer": {}, "processing": {}},
                {"ok": True, "answer": {"display": {"summary": "ok", "bullets": []}}, "processing": {}},
            ],
        ):
            result = mod._run_query(
                pathlib.Path("."),
                cfg="/tmp/cfg",
                data="/tmp/data",
                query="q",
                timeout_s=1.0,
                lock_retries=2,
                lock_retry_wait_s=0.0,
            )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("attempt"), 2)
        self.assertEqual(result.get("attempts"), 3)

    def test_run_query_once_sets_metadata_only_env_when_enabled(self) -> None:
        mod = _load_module()
        captured: dict[str, str] = {}

        class _Proc:
            returncode = 0
            stdout = "{}"
            stderr = ""

        def _fake_run(cmd, cwd, env, capture_output, text, check, timeout):  # noqa: ARG001
            captured["AUTOCAPTURE_QUERY_METADATA_ONLY"] = str(env.get("AUTOCAPTURE_QUERY_METADATA_ONLY") or "")
            captured["AUTOCAPTURE_ADV_HARD_VLM_MODE"] = str(env.get("AUTOCAPTURE_ADV_HARD_VLM_MODE") or "")
            captured["AUTOCAPTURE_QUERY_METADATA_ONLY_ALLOW_HARD_VLM"] = str(
                env.get("AUTOCAPTURE_QUERY_METADATA_ONLY_ALLOW_HARD_VLM") or ""
            )
            captured["AUTOCAPTURE_QUERY_IMAGE_PATH"] = str(env.get("AUTOCAPTURE_QUERY_IMAGE_PATH") or "")
            return _Proc()

        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_ADV_QUERY_INPROC": "0"}, clear=False),
            mock.patch.object(mod.subprocess, "run", side_effect=_fake_run),
        ):
            out = mod._run_query_once(
                pathlib.Path("."),
                cfg="/tmp/cfg",
                data="/tmp/data",
                query="q",
                image_path="/tmp/frame.png",
                metadata_only=True,
                timeout_s=1.0,
            )
        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(captured.get("AUTOCAPTURE_QUERY_METADATA_ONLY"), "1")
        self.assertEqual(captured.get("AUTOCAPTURE_ADV_HARD_VLM_MODE"), "off")
        self.assertEqual(captured.get("AUTOCAPTURE_QUERY_METADATA_ONLY_ALLOW_HARD_VLM"), "0")
        self.assertEqual(captured.get("AUTOCAPTURE_QUERY_IMAGE_PATH"), "")

    def test_run_query_once_uses_inproc_runner_when_enabled(self) -> None:
        mod = _load_module()
        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_ADV_QUERY_INPROC": "1"}, clear=False),
            mock.patch.object(mod, "_run_query_inproc", return_value={"ok": True, "answer": {}, "processing": {}}) as inproc_mock,
            mock.patch.object(mod.subprocess, "run") as subproc_mock,
        ):
            out = mod._run_query_once(
                pathlib.Path("."),
                cfg="/tmp/cfg",
                data="/tmp/data",
                query="q",
                image_path="/tmp/frame.png",
                metadata_only=True,
                timeout_s=1.0,
            )
        self.assertTrue(bool(out.get("ok", False)))
        inproc_mock.assert_called_once()
        subproc_mock.assert_not_called()

    def test_run_query_inproc_reuses_single_facade_session(self) -> None:
        mod = _load_module()

        class _Facade:
            def __init__(self) -> None:
                self.calls: list[tuple[str, bool]] = []
                self.closed = False

            def query(self, text: str, *, schedule_extract: bool = False) -> dict[str, object]:
                self.calls.append((str(text), bool(schedule_extract)))
                return {"answer": {"display": {"summary": str(text), "bullets": []}}, "processing": {}}

            def shutdown(self) -> None:
                self.closed = True

        facade = _Facade()
        env = {
            "AUTOCAPTURE_CONFIG_DIR": "/tmp/cfg",
            "AUTOCAPTURE_DATA_DIR": "/tmp/data",
            "AUTOCAPTURE_QUERY_METADATA_ONLY": "1",
        }
        with mock.patch("autocapture_nx.ux.facade.create_facade", return_value=facade) as create_mock:
            out1 = mod._run_query_inproc(root=pathlib.Path("."), query="q1", env=env)
            out2 = mod._run_query_inproc(root=pathlib.Path("."), query="q2", env=env)
            mod._shutdown_inproc_runner()
        self.assertTrue(bool(out1.get("ok", False)))
        self.assertTrue(bool(out2.get("ok", False)))
        self.assertEqual(create_mock.call_count, 1)
        self.assertEqual(len(facade.calls), 2)
        self.assertTrue(bool(facade.closed))

    def test_instance_lock_detection_from_stderr(self) -> None:
        mod = _load_module()
        result = {"ok": False, "error": "boot_failed", "stderr": "ConfigError: instance_lock_held"}
        self.assertTrue(mod._is_instance_lock_error(result))

    def test_contractize_query_failure_emits_deterministic_no_evidence_contract(self) -> None:
        mod = _load_module()
        raw = {"ok": False, "error": "query_timeout:30.0s", "answer": {}, "processing": {}}
        out1 = mod._contractize_query_failure(raw, query="what changed", case_id="GQ9")
        out2 = mod._contractize_query_failure(raw, query="what changed", case_id="GQ9")
        self.assertTrue(bool(out1.get("ok", False)))
        answer = out1.get("answer", {}) if isinstance(out1.get("answer", {}), dict) else {}
        processing = out1.get("processing", {}) if isinstance(out1.get("processing", {}), dict) else {}
        trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
        self.assertEqual(str(answer.get("state") or ""), "no_evidence")
        self.assertTrue(str(answer.get("summary") or "").strip())
        self.assertTrue(str(trace.get("query_run_id") or "").strip())
        self.assertEqual(out1, out2)

    def test_expected_contains_all_and_path_checks_pass(self) -> None:
        mod = _load_module()
        case = {
            "id": "QX",
            "expected_contains_all": ["Remote Desktop Web Client", "hostname"],
            "expected_paths": [
                {"path": "answer.state", "equals": "ok"},
                {"path": "answer.display.summary", "contains": "Remote Desktop Web Client"},
            ],
        }
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": "Browser window: Remote Desktop Web Client hostname outlook.office.com", "bullets": []},
            },
            "processing": {"query_trace": {"winner": "classic"}},
        }
        eval_out = mod._evaluate_expected(case, result, result["answer"]["display"]["summary"], [])
        self.assertTrue(eval_out["evaluated"])
        self.assertTrue(eval_out["passed"])
        self.assertGreaterEqual(len(eval_out["checks"]), 4)

    def test_expected_exact_summary_passes_with_whitespace_and_case_normalization(self) -> None:
        mod = _load_module()
        case = {"id": "QX", "expected_exact_summary": "Focused Window: Outlook VDI"}
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": " focused   window:   outlook vdi ", "bullets": []},
            },
            "processing": {"query_trace": {"winner": "classic"}},
        }
        eval_out = mod._evaluate_expected(case, result, result["answer"]["display"]["summary"], [])
        self.assertTrue(eval_out["evaluated"])
        self.assertTrue(eval_out["passed"])
        self.assertTrue(any(c.get("key") == "expected_exact_summary" for c in eval_out.get("checks", [])))

    def test_expected_exact_surface_fails_on_partial_match(self) -> None:
        mod = _load_module()
        case = {"id": "QX", "expected_exact_surface": "Focused window: Outlook VDI\nCount: 7"}
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": "Focused window: Outlook VDI", "bullets": ["Count: 7", "Extra: partial"]},
            },
            "processing": {"query_trace": {"winner": "classic"}},
        }
        eval_out = mod._evaluate_expected(case, result, result["answer"]["display"]["summary"], result["answer"]["display"]["bullets"])
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])
        self.assertTrue(
            any(
                isinstance(c, dict)
                and c.get("key") == "expected_exact_surface"
                and not bool(c.get("match"))
                for c in eval_out.get("checks", [])
            )
        )

    def test_expected_answer_flatten_backcompat(self) -> None:
        mod = _load_module()
        case = {"expected_answer": {"subject": "Task Set Up Open Invoice", "buttons": ["COMPLETE", "VIEW DETAILS"]}}
        result = {"answer": {"display": {"summary": "subject: Task Set Up Open Invoice; actions: COMPLETE, VIEW DETAILS", "bullets": []}}}
        eval_out = mod._evaluate_expected(case, result, "subject: Task Set Up Open Invoice; actions: COMPLETE, VIEW DETAILS", [])
        self.assertTrue(eval_out["evaluated"])
        self.assertTrue(eval_out["passed"])

    def test_strict_contains_all_ignores_support_only_lines(self) -> None:
        mod = _load_module()
        case = {
            "id": "Q4",
            "expected_contains_all": ["Your record was updated on Feb 02, 2026 - 12:08pm CST"],
        }
        result = {
            "answer": {
                "state": "ok",
                "display": {
                    "summary": "Record Activity entries: 2",
                    "bullets": [
                        "1. 12:08PMCST | garbled",
                        "support: Your record was updated on Feb 02, 2026 - 12:08pm CST",
                    ],
                    "fields": {"activity_count": "2"},
                },
            },
            "processing": {"metadata_only_query": True, "promptops_used": True, "hard_vlm": {"fields": {}}},
        }
        eval_out = mod._evaluate_expected(case, result, "Record Activity entries: 2", result["answer"]["display"]["bullets"], strict_expected_answer=True)
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])

    def test_strict_numeric_token_does_not_match_larger_number(self) -> None:
        mod = _load_module()
        case = {"id": "Q9", "expected_contains_all": ["16"]}
        result = {
            "answer": {
                "state": "ok",
                "display": {
                    "summary": "Console line colors: count_red=12, count_green=9, count_other=19",
                    "bullets": ["red_1: line", "support: line 163 has text"],
                    "fields": {"red_count": "12", "green_count": "9", "other_count": "19"},
                },
            },
            "processing": {"metadata_only_query": True, "promptops_used": True, "hard_vlm": {"fields": {}}},
        }
        eval_out = mod._evaluate_expected(
            case,
            result,
            result["answer"]["display"]["summary"],
            result["answer"]["display"]["bullets"],
            strict_expected_answer=True,
        )
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])

    def test_strict_q1_fails_on_partial_visibility_language(self) -> None:
        mod = _load_module()
        case = {"id": "Q1"}
        result = {
            "answer": {
                "state": "ok",
                "display": {
                    "summary": "Visible top-level windows: 7",
                    "bullets": ["1. Outlook VDI (vdi; partially_occluded)"],
                    "fields": {"window_count": "7"},
                },
            },
            "processing": {
                "metadata_only_query": True,
                "promptops_used": True,
                "hard_vlm": {"fields": {}},
                "attribution": {
                    "providers": [
                        {"provider_id": "builtin.observation.graph", "contribution_bp": 10000},
                    ]
                },
            },
        }
        eval_out = mod._evaluate_expected(
            case,
            result,
            result["answer"]["display"]["summary"],
            result["answer"]["display"]["bullets"],
            strict_expected_answer=True,
            enforce_true_strict=True,
        )
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])
        checks = eval_out.get("checks", [])
        self.assertTrue(
            any(
                isinstance(c, dict)
                and c.get("key") == "no_partial_or_truncated_surface"
                and "partial_visibility_language" in list(c.get("markers") or [])
                for c in checks
            )
        )

    def test_strict_provider_gate_flags_disallowed_answer_provider_activity(self) -> None:
        mod = _load_module()
        case = {"id": "Q2"}
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": "Focused window: Outlook VDI", "bullets": [], "fields": {"focused_window": "Outlook VDI"}},
            },
            "processing": {
                "metadata_only_query": True,
                "promptops_used": True,
                "hard_vlm": {"fields": {}},
                "attribution": {
                    "providers": [
                        {"provider_id": "builtin.observation.graph", "contribution_bp": 10000},
                        {"provider_id": "hard_vlm.direct", "claim_count": 1, "citation_count": 1, "contribution_bp": 0},
                    ]
                },
            },
        }
        eval_out = mod._evaluate_expected(
            case,
            result,
            result["answer"]["display"]["summary"],
            [],
            strict_expected_answer=True,
            enforce_true_strict=True,
        )
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])
        checks = eval_out.get("checks", [])
        self.assertTrue(
            any(
                isinstance(c, dict)
                and c.get("key") == "disallowed_answer_provider_activity"
                and not bool(c.get("present"))
                for c in checks
            )
        )

    def test_strict_provider_gate_requires_positive_non_disallowed_contribution(self) -> None:
        mod = _load_module()
        case = {"id": "H8", "expected_answer": {"today_unread_indicator_count": 7}}
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": "Today unread-indicator rows: 7", "bullets": [], "fields": {"today_unread_indicator_count": 7}},
            },
            "processing": {
                "hard_vlm": {"fields": {"today_unread_indicator_count": 7}},
                "attribution": {
                    "providers": [
                        {"provider_id": "builtin.answer.synth_vllm_localhost", "contribution_bp": 0},
                        {"provider_id": "hard_vlm.direct", "claim_count": 1, "citation_count": 1, "contribution_bp": 0},
                    ]
                },
            },
        }
        eval_out = mod._evaluate_expected(
            case,
            result,
            result["answer"]["display"]["summary"],
            [],
            strict_expected_answer=True,
            enforce_true_strict=True,
        )
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])
        checks = eval_out.get("checks", [])
        self.assertTrue(
            any(
                isinstance(c, dict)
                and c.get("key") == "non_disallowed_positive_provider_contribution"
                and not bool(c.get("present"))
                for c in checks
            )
        )

    def test_true_strict_enforcement_is_opt_in(self) -> None:
        mod = _load_module()
        case = {"id": "Q1"}
        result = {
            "answer": {
                "state": "ok",
                "display": {
                    "summary": "Visible top-level windows: 7",
                    "bullets": ["1. Outlook VDI (vdi; partially_occluded)"],
                    "fields": {"window_count": "7"},
                },
            },
            "processing": {
                "metadata_only_query": True,
                "promptops_used": True,
                "hard_vlm": {"fields": {}},
            },
        }
        eval_out = mod._evaluate_expected(
            case,
            result,
            result["answer"]["display"]["summary"],
            result["answer"]["display"]["bullets"],
            strict_expected_answer=True,
            enforce_true_strict=False,
        )
        self.assertTrue(eval_out["evaluated"])
        self.assertTrue(eval_out["passed"])

    def test_q_series_metadata_only_enforcement_uses_structured_display(self) -> None:
        mod = _load_module()
        case = {"id": "Q1"}
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": "Visible top-level windows: 4", "bullets": [], "fields": {"window_count": "4"}},
            },
            "processing": {
                "metadata_only_query": True,
                "promptops_used": True,
            },
        }
        eval_out = mod._evaluate_expected(case, result, result["answer"]["display"]["summary"], [])
        self.assertTrue(eval_out["evaluated"])
        self.assertTrue(eval_out["passed"])
        checks = eval_out.get("checks", [])
        self.assertTrue(any(isinstance(c, dict) and c.get("key") == "metadata_structured_display" and c.get("present") for c in checks))

    def test_q_series_metadata_only_enforcement_fails_without_structured_display(self) -> None:
        mod = _load_module()
        case = {"id": "Q1"}
        result = {
            "answer": {
                "state": "ok",
                "display": {"summary": "indeterminate", "bullets": [], "fields": {}},
            },
            "processing": {
                "metadata_only_query": True,
                "promptops_used": True,
            },
        }
        eval_out = mod._evaluate_expected(case, result, result["answer"]["display"]["summary"], [])
        self.assertTrue(eval_out["evaluated"])
        self.assertFalse(eval_out["passed"])

    def test_no_checks_is_not_evaluated(self) -> None:
        mod = _load_module()
        eval_out = mod._evaluate_expected({"id": "Q0"}, {"answer": {}}, "", [])
        self.assertFalse(eval_out["evaluated"])
        self.assertIsNone(eval_out["passed"])

    def test_main_fails_closed_when_required_plugin_gate_failed(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "plugins": {"load_report": {"loaded": ["builtin.a"]}, "required_gate": {"ok": False, "missing_required": ["builtin.b"]}},
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text("[]", encoding="utf-8")
            with mock.patch.object(mod, "_repo_root", return_value=root):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--output", str(root / "out.json")])
            self.assertEqual(rc, 2)

    def test_main_runtime_mode_rejects_report_conflict(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(json.dumps({"config_dir": "/tmp/cfg", "data_dir": "/tmp/data"}), encoding="utf-8")
            cases = root / "cases.json"
            cases.write_text("[]", encoding="utf-8")
            with mock.patch.object(mod, "_repo_root", return_value=root):
                rc = mod.main(
                    [
                        "--report",
                        str(report),
                        "--config-dir",
                        "/tmp/cfg",
                        "--data-dir",
                        "/tmp/data",
                        "--cases",
                        str(cases),
                    ]
                )
            self.assertEqual(rc, 2)

    def test_main_runtime_mode_uses_config_data_without_report(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "cfg"
            data = root / "data"
            cfg.mkdir(parents=True, exist_ok=True)
            data.mkdir(parents=True, exist_ok=True)
            cases = root / "cases.json"
            cases.write_text("[]", encoding="utf-8")
            output = root / "out.json"
            source_report = root / "runtime_source.json"
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": True, "models": ["m"]}),
            ):
                rc = mod.main(
                    [
                        "--config-dir",
                        str(cfg),
                        "--data-dir",
                        str(data),
                        "--source-report",
                        str(source_report),
                        "--cases",
                        str(cases),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(rc, 0)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(parsed.get("report") or ""), str(source_report))
            self.assertEqual(str(parsed.get("source_report") or ""), str(source_report))

    def test_main_strict_runtime_mode_uses_profile_sha(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config" / "profiles").mkdir(parents=True, exist_ok=True)
            profile = root / "config" / "profiles" / "golden_full.json"
            profile.write_text(json.dumps({"profile": "golden"}), encoding="utf-8")
            cfg = root / "cfg"
            data = root / "data"
            cfg.mkdir(parents=True, exist_ok=True)
            data.mkdir(parents=True, exist_ok=True)
            cases = root / "cases.json"
            cases.write_text(
                json.dumps(
                    [
                        {
                            "id": "X1",
                            "question": "q1",
                            "requires_vlm": False,
                            "expected_contains_all": ["ok"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            output = root / "out.json"
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": True, "models": ["m"]}),
                mock.patch.object(
                    mod,
                    "_run_query",
                    return_value={
                        "ok": True,
                        "answer": {"state": "ok", "display": {"summary": "ok", "bullets": []}},
                        "processing": {"query_trace": {"stage_ms": {"total": 1.0}}},
                    },
                ),
            ):
                rc = mod.main(
                    [
                        "--config-dir",
                        str(cfg),
                        "--data-dir",
                        str(data),
                        "--cases",
                        str(cases),
                        "--metadata-only",
                        "--strict-all",
                        "--output",
                        str(output),
                    ]
                )
            self.assertNotEqual(rc, 2)
            self.assertTrue(output.exists())

    def test_main_can_continue_when_vllm_unavailable_if_allowed(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id": "Q1", "question": "q", "expected_contains_all": ["ok"]}]), encoding="utf-8")
            output = root / "out.json"
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": False, "error": "down"}),
                mock.patch.object(mod, "_run_query", return_value={"ok": True, "answer": {"display": {"summary": "ok", "bullets": []}}, "processing": {}}),
            ):
                rc = mod.main(
                    [
                        "--report",
                        str(report),
                        "--cases",
                        str(cases),
                        "--output",
                        str(output),
                        "--allow-vllm-unavailable",
                    ]
                )
            self.assertEqual(rc, 0)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(parsed.get("ok"))
            self.assertEqual(parsed.get("evaluated_total"), 0)
            self.assertEqual(parsed.get("rows_skipped"), 1)

    def test_main_skips_vlm_cases_when_unstable(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(
                json.dumps(
                    [
                        {"id": "Q1", "question": "q1"},
                        {"id": "X1", "question": "x1", "requires_vlm": False, "expected_contains_all": ["ok"]},
                    ]
                ),
                encoding="utf-8",
            )
            output = root / "out.json"
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": False, "error": "down"}),
                mock.patch.object(mod, "_run_query", return_value={"ok": True, "answer": {"display": {"summary": "ok", "bullets": []}}, "processing": {}}),
            ):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--output", str(output)])
            self.assertEqual(rc, 0)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(parsed.get("ok"))
            self.assertEqual(parsed.get("rows_skipped"), 1)
            self.assertEqual(parsed.get("evaluated_total"), 1)
            rows = parsed.get("rows", [])
            self.assertEqual(len(rows), 2)
            self.assertTrue(bool(rows[0].get("skipped", False)))
            self.assertFalse(bool(rows[1].get("skipped", False)))

    def test_main_metadata_only_does_not_skip_when_vlm_unstable(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id": "Q1", "question": "q1", "expected_contains_all": ["ok"]}]), encoding="utf-8")
            output = root / "out.json"
            preflight_mock = mock.Mock(return_value={"ok": False, "error": "down"})
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", preflight_mock),
                mock.patch.object(mod, "_run_query", return_value={"ok": True, "answer": {"display": {"summary": "ok", "bullets": []}}, "processing": {}}),
            ):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--metadata-only", "--output", str(output)])
            self.assertEqual(rc, 0)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(parsed.get("rows_skipped"), 0)
            self.assertEqual(parsed.get("evaluated_total"), 1)
            preflight_mock.assert_not_called()

    def test_main_metadata_only_defaults_repro_runs_to_one(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "determinism_contract": {"repro_runs": 3},
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id": "Q1", "question": "q1", "expected_contains_all": ["ok"]}]), encoding="utf-8")
            output = root / "out.json"
            run_calls: list[str] = []

            def _fake_run_query(*args, **kwargs):  # noqa: ANN001
                run_calls.append("x")
                return {"ok": True, "answer": {"display": {"summary": "ok", "bullets": []}}, "processing": {}}

            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": False, "error": "down"}),
                mock.patch.object(mod, "_run_query", side_effect=_fake_run_query),
            ):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--metadata-only", "--output", str(output)])
            self.assertEqual(rc, 0)
            self.assertEqual(len(run_calls), 1)

    def test_main_skip_mode_does_not_run_extra_stability_probe_after_failed_preflight(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id": "Q1", "question": "q1"}]), encoding="utf-8")
            output = root / "out.json"
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": False, "error": "down"}),
                mock.patch.object(mod, "_probe_vllm_stability", side_effect=AssertionError("stability_probe_should_not_run")),
            ):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--output", str(output)])
            self.assertEqual(rc, 0)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(parsed.get("rows_skipped"), 1)

    def test_gq_case_defaults_to_vlm_required(self) -> None:
        mod = _load_module()
        self.assertTrue(mod._case_requires_vlm({"id": "GQ1"}))
        self.assertTrue(mod._case_requires_vlm({"id": "gq20"}))
        self.assertFalse(mod._case_requires_vlm({"id": "X1"}))
        self.assertFalse(mod._case_requires_vlm({"id": "GQ1", "requires_vlm": False}))

    def test_canonical_signature_is_stable(self) -> None:
        mod = _load_module()
        result = {
            "answer": {"display": {"summary": "abc", "bullets": ["x"], "fields": {"k": "v"}}},
            "processing": {"query_trace": {"winner": "classic", "method": "state"}, "hard_vlm": {"fields": {"h": 1}}},
        }
        sig1 = mod._canonical_signature(result, "abc", ["x"])
        sig2 = mod._canonical_signature(result, "abc", ["x"])
        self.assertEqual(sig1, sig2)

    def test_main_strict_fails_on_profile_checksum_mismatch(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config" / "profiles").mkdir(parents=True, exist_ok=True)
            profile = root / "config" / "profiles" / "golden_full.json"
            profile.write_text(json.dumps({"x": 1}), encoding="utf-8")
            bad_sha = "f" * 64
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "profile_sha256": bad_sha,
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text("[]", encoding="utf-8")
            with mock.patch.object(mod, "_repo_root", return_value=root):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--strict-all", "--output", str(root / "o.json")])
            self.assertEqual(rc, 2)

    def test_main_strict_fails_closed_when_vllm_unavailable(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config" / "profiles").mkdir(parents=True, exist_ok=True)
            profile = root / "config" / "profiles" / "golden_full.json"
            profile.write_text(json.dumps({"profile": "golden"}), encoding="utf-8")
            profile_sha = hashlib.sha256(profile.read_bytes()).hexdigest()
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "profile_sha256": profile_sha,
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id": "Q1", "question": "q1"}]), encoding="utf-8")
            output = root / "out.json"
            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": False, "error": "down"}),
            ):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--strict-all", "--output", str(output)])
            self.assertEqual(rc, 2)
            self.assertFalse(output.exists())

    def test_main_strict_requires_metadata_only(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config" / "profiles").mkdir(parents=True, exist_ok=True)
            profile = root / "config" / "profiles" / "golden_full.json"
            profile.write_text(json.dumps({"profile": "golden"}), encoding="utf-8")
            profile_sha = hashlib.sha256(profile.read_bytes()).hexdigest()
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": "/tmp/cfg",
                        "data_dir": "/tmp/data",
                        "profile_sha256": profile_sha,
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text("[]", encoding="utf-8")
            output = root / "out.json"
            with mock.patch.object(mod, "_repo_root", return_value=root):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--strict-all", "--output", str(output)])
            self.assertEqual(rc, 2)
            self.assertFalse(output.exists())

    def test_main_seeds_vlm_api_key_from_config_for_preflight(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "cfg"
            cfg.mkdir(parents=True, exist_ok=True)
            (cfg / "user.json").write_text(
                json.dumps(
                    {
                        "plugins": {
                            "settings": {
                                "builtin.vlm.vllm_localhost": {"api_key": "cfg-key"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": str(cfg),
                        "data_dir": "/tmp/data",
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text("[]", encoding="utf-8")
            output = root / "out.json"

            seen_key: dict[str, str] = {}

            def _probe(*args: object, **kwargs: object) -> dict[str, object]:
                seen_key["value"] = str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "")
                return {"ok": True, "models": ["OpenGVLab/InternVL3_5-8B-HF"]}

            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", side_effect=_probe),
                mock.patch.dict(os.environ, {"AUTOCAPTURE_VLM_API_KEY": ""}, clear=False),
            ):
                rc = mod.main(["--report", str(report), "--cases", str(cases), "--output", str(output)])
            self.assertEqual(rc, 0)
            self.assertEqual(seen_key.get("value"), "cfg-key")

    def test_metadata_only_does_not_pass_report_image_path_to_query(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "cfg"
            data = root / "data"
            cfg.mkdir(parents=True, exist_ok=True)
            data.mkdir(parents=True, exist_ok=True)
            image = root / "frame.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "config_dir": str(cfg),
                        "data_dir": str(data),
                        "image_path": str(image),
                        "plugins": {
                            "load_report": {"loaded": ["builtin.a"]},
                            "required_gate": {"ok": True, "missing_required": [], "failed_required": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id": "Q1", "question": "q", "expected_contains_all": ["ok"]}]), encoding="utf-8")
            output = root / "out.json"
            seen_image_path: dict[str, str] = {}

            def _mock_run_query(*args: object, **kwargs: object) -> dict[str, object]:
                seen_image_path["value"] = str(kwargs.get("image_path") or "")
                return {"ok": True, "answer": {"display": {"summary": "ok", "bullets": []}}, "processing": {}}

            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", return_value={"ok": True}),
                mock.patch.object(mod, "_run_query", side_effect=_mock_run_query),
            ):
                rc = mod.main(
                    [
                        "--report",
                        str(report),
                        "--cases",
                        str(cases),
                        "--output",
                        str(output),
                        "--metadata-only",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(seen_image_path.get("value"), "")


if __name__ == "__main__":
    unittest.main()
