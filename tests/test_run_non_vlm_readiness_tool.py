from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunNonVlmReadinessToolTests(unittest.TestCase):
    def test_extract_json_tail_reads_last_object_line(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_1")
        text = "noise\n{\"ok\":false}\n{\"ok\":true,\"x\":1}\n"
        out = mod._extract_json_tail(text)  # noqa: SLF001
        self.assertEqual(out, {"ok": True, "x": 1})

    def test_main_fails_fast_when_db_missing(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_2")
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "out.json"
            rc = mod.main(
                [
                    "--dataroot",
                    str(Path(td) / "missing_root"),
                    "--output",
                    str(out_path),
                    "--no-run-pytest",
                    "--no-run-gates",
                    "--no-run-query-eval",
                    "--no-revalidate-markers",
                ]
            )
            self.assertEqual(rc, 2)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            self.assertEqual(str(payload.get("error") or ""), "metadata_db_missing")

    def test_pick_python_prefers_repo_venv_when_current_missing_pytest(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_3")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            venv_py = root / ".venv" / "bin" / "python"
            venv_py.parent.mkdir(parents=True, exist_ok=True)
            venv_py.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            with mock.patch.object(mod, "sys", autospec=True) as fake_sys:
                fake_sys.executable = "/usr/bin/python3"
                with mock.patch.object(mod, "_has_module", autospec=True) as has_module:
                    has_module.side_effect = lambda py, module: str(py) == str(venv_py)
                    out = mod._pick_python(root, "")  # noqa: SLF001
            self.assertEqual(out, str(venv_py))

    def test_transient_db_error_detector_matches_operational_error(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_4")
        row = {
            "stdout_tail": "{\"ok\":false,\"error\":\"OperationalError:disk I/O error\"}",
            "stderr_tail": "",
            "stdout_json": {"ok": False},
        }
        self.assertTrue(bool(mod._is_transient_db_error(row)))  # noqa: SLF001

    def test_dpapi_failure_detector_matches_query_eval_failure(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_5")
        row = {
            "stdout_tail": "",
            "stderr_tail": "RuntimeError: DPAPI unprotect requires Windows",
            "stdout_json": None,
        }
        self.assertTrue(bool(mod._is_dpapi_windows_failure(row)))  # noqa: SLF001

    def test_build_query_eval_env_isolates_data_dir_and_pins_metadata(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_6")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataroot = root / "dataroot"
            cfg_dir = root / "cfg"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "user.json").write_text(
                json.dumps({"storage": {"metadata_path": str(dataroot / "metadata.db")}}),
                encoding="utf-8",
            )
            env = mod._build_query_eval_env(  # noqa: SLF001
                base_env={"AUTOCAPTURE_CONFIG_DIR": str(cfg_dir), "AUTOCAPTURE_DATA_DIR": str(dataroot)},
                run_dir=root / "run",
                dataroot=dataroot,
                metadata_db_path=dataroot / "metadata.live.db",
            )
            self.assertIn("AUTOCAPTURE_CONFIG_DIR", env)
            self.assertIn("AUTOCAPTURE_DATA_DIR", env)
            self.assertNotEqual(str(env["AUTOCAPTURE_DATA_DIR"]), str(dataroot))
            user_payload = json.loads((Path(env["AUTOCAPTURE_CONFIG_DIR"]) / "user.json").read_text(encoding="utf-8"))
            storage = user_payload.get("storage", {})
            self.assertEqual(str(storage.get("metadata_path") or ""), str(dataroot / "metadata.live.db"))
            plugins = user_payload.get("plugins", {})
            locks = plugins.get("locks", {}) if isinstance(plugins, dict) else {}
            self.assertFalse(bool(locks.get("enforce", True)))

    def test_retryable_query_step_error_detects_lock_marker(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_7")
        row = {
            "stdout_tail": "{\"ok\": false, \"error\": \"kernel_boot_failed:ConfigError:instance_lock_held\"}",
            "stderr_tail": "",
            "stdout_json": None,
        }
        self.assertTrue(bool(mod._is_retryable_query_step_error(row)))  # noqa: SLF001

    def test_run_preflight_aggregates_three_checks(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_8")
        with mock.patch.object(mod, "_http_preflight", autospec=True) as http_pre, mock.patch.object(
            mod, "_metadata_db_preflight", autospec=True
        ) as db_pre, mock.patch.object(mod, "_popup_query_preflight", autospec=True) as popup_pre:
            http_pre.side_effect = [
                {"ok": True, "status": 200},
                {"ok": True, "status": 200},
            ]
            db_pre.return_value = {"ok": True, "record_count": 1}
            popup_pre.return_value = {"ok": True, "popup_state": "ok"}
            out = mod._run_preflight(  # noqa: SLF001
                db_path=Path("/tmp/x.db"),
                sidecar_url="http://127.0.0.1:7411/health",
                vlm_url="http://127.0.0.1:8000/health",
                popup_base_url="http://127.0.0.1:7411",
                popup_path="/api/query/popup",
                auth_token_path="/api/auth/token",
                popup_query="status check",
                popup_max_citations=6,
                timeout_s=1.0,
            )
        self.assertTrue(bool(out.get("ok", False)))
        self.assertIn("sidecar_7411", out)
        self.assertIn("vlm_8000", out)
        self.assertIn("metadata_db", out)
        self.assertIn("popup_query", out)

    def test_popup_preflight_fails_on_forbidden_block_reason(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_8b")
        with mock.patch.object(mod, "_http_json_request", autospec=True) as req:
            req.side_effect = [
                {
                    "ok": True,
                    "status": 200,
                    "json": {"token": "tok_test"},
                    "body": "{\"token\":\"tok_test\"}",
                },
                {
                    "ok": True,
                    "status": 200,
                    "json": {
                        "ok": True,
                        "state": "not_available_yet",
                        "processing_blocked_reason": "query_compute_disabled",
                    },
                    "body": "{}",
                },
            ]
            out = mod._popup_query_preflight(  # noqa: SLF001
                sidecar_base_url="http://127.0.0.1:7411",
                popup_path="/api/query/popup",
                auth_token_path="/api/auth/token",
                query_text="status check",
                max_citations=6,
                timeout_s=1.0,
            )
        self.assertFalse(bool(out.get("ok", True)))
        self.assertEqual(str(out.get("error") or ""), "popup_forbidden_block_reason")
        reasons = set(out.get("forbidden_reasons", []))
        self.assertIn("query_compute_disabled", reasons)

    def test_main_returns_preflight_failed_when_required(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_9")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataroot = root / "data"
            dataroot.mkdir(parents=True, exist_ok=True)
            db = dataroot / "metadata.db"
            con = sqlite3.connect(db)
            con.execute("create table metadata(record_type text)")
            con.commit()
            con.close()
            out_path = root / "out.json"
            with mock.patch.object(mod, "_repo_root", return_value=root), mock.patch.object(
                mod, "_run_preflight", return_value={"ok": False, "sidecar_7411": {"ok": False}}
            ):
                rc = mod.main(
                    [
                        "--dataroot",
                        str(dataroot),
                        "--output",
                        str(out_path),
                        "--no-run-pytest",
                        "--no-run-gates",
                        "--no-run-query-eval",
                        "--no-run-synthetic-gauntlet",
                        "--no-revalidate-markers",
                        "--require-preflight",
                    ]
                )
            self.assertEqual(rc, 3)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("error") or ""), "preflight_failed")

    def test_metadata_db_preflight_retries_transient_errors(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_10")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "metadata.db"
            con = sqlite3.connect(db)
            con.execute("create table metadata(record_type text)")
            con.commit()
            con.close()

            real_connect = sqlite3.connect
            calls = {"n": 0}

            def _connect(*args, **kwargs):  # type: ignore[no-untyped-def]
                calls["n"] += 1
                if calls["n"] == 1:
                    raise sqlite3.OperationalError("disk I/O error")
                return real_connect(*args, **kwargs)

            with mock.patch.object(mod.sqlite3, "connect", side_effect=_connect):
                out = mod._metadata_db_preflight(db)  # noqa: SLF001
            self.assertTrue(bool(out.get("ok", False)))
            self.assertEqual(int(out.get("attempts", 0) or 0), 2)
            self.assertTrue(bool(out.get("retried", False)))

    def test_resolve_metadata_db_path_prefers_live_when_primary_unreadable(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_11")
        with tempfile.TemporaryDirectory() as td:
            dataroot = Path(td)
            primary = dataroot / "metadata.db"
            live = dataroot / "metadata.live.db"
            primary.write_text("", encoding="utf-8")
            live.write_text("", encoding="utf-8")
            with mock.patch.object(mod, "_metadata_db_preflight", autospec=True) as probe:
                probe.side_effect = [
                    {"ok": False, "error": "OperationalError:disk I/O error"},
                    {"ok": True, "record_count": 10},
                ]
                selected, details = mod._resolve_metadata_db_path(  # noqa: SLF001
                    dataroot=dataroot,
                    explicit_db="",
                )
        self.assertEqual(selected, live)
        self.assertEqual(str(details.get("strategy") or ""), "fallback_live_readable")

    def test_failure_class_counts_normalize_known_and_generic_errors(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_11b")
        steps = [
            {
                "id": "query_eval_suite_generic20_metadata_only",
                "ok": False,
                "stdout_json": {"error": "kernel_boot_failed:ConfigError:instance_lock_held"},
                "stderr_tail": "",
                "stdout_tail": "",
            },
            {
                "id": "gate_plugin_enablement",
                "ok": False,
                "stdout_json": {"error": "strict_matrix_gate_failed"},
                "stderr_tail": "",
                "stdout_tail": "",
            },
            {
                "id": "synthetic_gauntlet_80_metadata_only",
                "ok": False,
                "stdout_json": {"error": "ignored"},
                "skipped": True,
                "stderr_tail": "",
                "stdout_tail": "",
            },
        ]
        out = mod._failure_class_counts(steps)  # noqa: SLF001
        self.assertEqual(int(out.get("instance_lock_held", 0) or 0), 1)
        self.assertEqual(int(out.get("strict_matrix_gate_failed", 0) or 0), 1)
        self.assertNotIn("ignored", out)

    def test_main_includes_resolution_on_preflight_failure(self) -> None:
        mod = _load_module("tools/run_non_vlm_readiness.py", "run_non_vlm_readiness_tool_12")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataroot = root / "data"
            dataroot.mkdir(parents=True, exist_ok=True)
            db = dataroot / "metadata.db"
            con = sqlite3.connect(db)
            con.execute("create table metadata(record_type text)")
            con.commit()
            con.close()
            out_path = root / "out.json"
            with mock.patch.object(mod, "_repo_root", return_value=root), mock.patch.object(
                mod, "_resolve_metadata_db_path", return_value=(db, {"selected": str(db), "strategy": "primary_readable"})
            ), mock.patch.object(mod, "_run_preflight", return_value={"ok": False}):
                rc = mod.main(
                    [
                        "--dataroot",
                        str(dataroot),
                        "--output",
                        str(out_path),
                        "--no-run-pytest",
                        "--no-run-gates",
                        "--no-run-query-eval",
                        "--no-run-synthetic-gauntlet",
                        "--no-revalidate-markers",
                        "--require-preflight",
                    ]
                )
            self.assertEqual(rc, 3)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("error") or ""), "preflight_failed")
            resolution = payload.get("metadata_db_resolution", {})
            self.assertEqual(str(resolution.get("strategy") or ""), "primary_readable")


if __name__ == "__main__":
    unittest.main()
