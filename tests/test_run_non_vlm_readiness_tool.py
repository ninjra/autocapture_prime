from __future__ import annotations

import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
