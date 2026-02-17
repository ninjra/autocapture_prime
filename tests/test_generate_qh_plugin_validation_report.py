from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/generate_qh_plugin_validation_report.py")
    spec = importlib.util.spec_from_file_location("generate_qh_plugin_validation_report_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GenerateQHPluginValidationReportTests(unittest.TestCase):
    def test_emits_report_from_latest_20_row_artifact(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_dir = root / "artifacts" / "advanced10"
            adv_dir.mkdir(parents=True, exist_ok=True)
            run_report = root / "artifacts" / "single_image_runs" / "single_x" / "report.json"
            run_report.parent.mkdir(parents=True, exist_ok=True)
            run_report.write_text(
                json.dumps(
                    {
                        "plugins": {
                            "load_report": {
                                "loaded": ["builtin.processing.sst.pipeline"],
                                "failed": [],
                                "skipped": [],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            rows = []
            for idx in range(20):
                rows.append(
                    {
                        "id": f"Q{idx+1}",
                        "question": "x",
                        "answer_state": "ok",
                        "summary": "ok",
                        "winner": "classic",
                        "stage_ms": {"total": 10.0},
                        "providers": [{"provider_id": "builtin.processing.sst.pipeline", "claim_count": 1, "citation_count": 1, "contribution_bp": 10000}],
                        "expected_eval": {"evaluated": True, "passed": True, "checks": []},
                    }
                )
            artifact = adv_dir / "advanced20_test.json"
            artifact.write_text(
                json.dumps(
                    {
                        "report": str(run_report.relative_to(root)),
                        "rows": rows,
                        "evaluated_total": 20,
                        "evaluated_passed": 20,
                        "evaluated_failed": 0,
                    }
                ),
                encoding="utf-8",
            )

            mod.ROOT = root
            mod.ADV_DIR = adv_dir
            rc = mod.main()
            self.assertEqual(rc, 0)
            md = root / "docs" / "reports" / "question-validation-plugin-trace-2026-02-13.md"
            js = root / "artifacts" / "advanced10" / "question_validation_plugin_trace_latest.json"
            self.assertTrue(md.exists())
            self.assertTrue(js.exists())
            self.assertIn("Plugin Inventory + Effectiveness", md.read_text(encoding="utf-8"))
            self.assertIn("Class Summary (Q/H/Other)", md.read_text(encoding="utf-8"))
            payload = json.loads(js.read_text(encoding="utf-8"))
            self.assertIn("class_rows", payload)
            self.assertIn("answer_state_confusion", payload)


if __name__ == "__main__":
    unittest.main()
