from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/query_latest_single.py")
    spec = importlib.util.spec_from_file_location("query_latest_single_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class QueryLatestSingleAuthTests(unittest.TestCase):
    def test_main_seeds_vlm_api_key_before_health_probe(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "cfg"
            cfg.mkdir(parents=True, exist_ok=True)
            (cfg / "user.json").write_text(
                json.dumps({"plugins": {"settings": {"builtin.vlm.vllm_localhost": {"api_key": "cfg-key"}}}}),
                encoding="utf-8",
            )
            run_dir = root / "artifacts" / "single_image_runs" / "single_1"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "report.json").write_text(
                json.dumps({"config_dir": str(cfg), "data_dir": str(root / "data")}),
                encoding="utf-8",
            )
            (root / "data").mkdir(parents=True, exist_ok=True)

            seen: dict[str, str] = {}

            def _probe():
                seen["key"] = str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "")
                return {"ok": True}

            with (
                mock.patch.object(mod, "_repo_root", return_value=root),
                mock.patch.object(mod, "check_external_vllm_ready", side_effect=_probe),
                mock.patch.object(
                    mod,
                    "_run_query",
                    return_value={
                        "answer": {"display": {"summary": "ok", "bullets": []}},
                        "processing": {"query_trace": {"query_run_id": "q1", "method": "state"}},
                    },
                ),
                mock.patch.dict(os.environ, {"AUTOCAPTURE_VLM_API_KEY": ""}, clear=False),
            ):
                rc = mod.main(["what song is playing", "--interactive", "off"])
            self.assertEqual(rc, 0)
            self.assertEqual(seen.get("key"), "cfg-key")


if __name__ == "__main__":
    unittest.main()
