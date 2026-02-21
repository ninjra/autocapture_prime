from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import tools.preflight_runtime as preflight


class PreflightRuntimeChecksTests(unittest.TestCase):
    def test_preflight_reports_failures(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.yaml"
            cfg_path.write_text("spool:\n  root_dir_linux: /missing\n", encoding="utf-8")
            with patch("sys.argv", ["preflight_runtime.py", "--config", str(cfg_path)]):
                rc = preflight.main()
            self.assertEqual(rc, 2)

    def test_preflight_can_pass_with_mocked_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spool = Path(td) / "spool"
            store = Path(td) / "store"
            spool.mkdir(parents=True, exist_ok=True)
            store.mkdir(parents=True, exist_ok=True)
            cfg_path = Path(td) / "cfg.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "spool:",
                        f"  root_dir_linux: {spool}",
                        "storage:",
                        f"  root_dir: {store}",
                        "vllm:",
                        "  base_url: http://127.0.0.1:8000",
                    ]
                ),
                encoding="utf-8",
            )
            ok_gpu = preflight.CheckResult("gpu.nvidia_smi", True, "ok")
            ok_vllm = preflight.CheckResult("vllm.health", True, "ok")
            with patch.object(preflight, "_check_gpu", return_value=ok_gpu), patch.object(
                preflight, "_check_vllm", return_value=ok_vllm
            ), patch("sys.argv", ["preflight_runtime.py", "--config", str(cfg_path)]):
                rc = preflight.main()
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
