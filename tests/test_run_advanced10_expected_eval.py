from __future__ import annotations

import importlib.util
import json
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

    def test_instance_lock_detection_from_stderr(self) -> None:
        mod = _load_module()
        result = {"ok": False, "error": "boot_failed", "stderr": "ConfigError: instance_lock_held"}
        self.assertTrue(mod._is_instance_lock_error(result))

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

    def test_expected_answer_flatten_backcompat(self) -> None:
        mod = _load_module()
        case = {"expected_answer": {"subject": "Task Set Up Open Invoice", "buttons": ["COMPLETE", "VIEW DETAILS"]}}
        result = {"answer": {"display": {"summary": "subject: Task Set Up Open Invoice; actions: COMPLETE, VIEW DETAILS", "bullets": []}}}
        eval_out = mod._evaluate_expected(case, result, "subject: Task Set Up Open Invoice; actions: COMPLETE, VIEW DETAILS", [])
        self.assertTrue(eval_out["evaluated"])
        self.assertTrue(eval_out["passed"])

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
            self.assertEqual(parsed.get("evaluated_total"), 1)

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


if __name__ == "__main__":
    unittest.main()
