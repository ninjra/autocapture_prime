from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/gate_q40_strict.py")
    spec = importlib.util.spec_from_file_location("gate_q40_strict_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GateQ40StrictTests(unittest.TestCase):
    def test_extract_counts_from_query_eval_report(self) -> None:
        mod = _load_module()
        counts = mod.extract_counts({"evaluated_total": 40, "rows_skipped": 0, "evaluated_failed": 0})
        self.assertEqual(counts["evaluated"], 40)
        self.assertEqual(counts["skipped"], 0)
        self.assertEqual(counts["failed"], 0)

    def test_extract_counts_from_matrix_report(self) -> None:
        mod = _load_module()
        counts = mod.extract_counts({"matrix_evaluated": 40, "matrix_skipped": 0, "matrix_failed": 0})
        self.assertEqual(counts["evaluated"], 40)
        self.assertEqual(counts["skipped"], 0)
        self.assertEqual(counts["failed"], 0)

    def test_main_passes_on_strict_40400(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            out = root / "gate.json"
            report.write_text(
                json.dumps(
                    {
                        "evaluated_total": 40,
                        "rows_skipped": 0,
                        "evaluated_failed": 0,
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--report", str(report), "--output", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))

    def test_main_fails_on_partial_eval(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            out = root / "gate.json"
            report.write_text(
                json.dumps(
                    {
                        "evaluated_total": 39,
                        "rows_skipped": 1,
                        "evaluated_failed": 0,
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--report", str(report), "--output", str(out)])
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("evaluated_mismatch", reasons)
            self.assertIn("skipped_mismatch", reasons)


if __name__ == "__main__":
    unittest.main()
