from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/gate_real_corpus_strict.py")
    spec = importlib.util.spec_from_file_location("gate_real_corpus_strict_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GateRealCorpusStrictTests(unittest.TestCase):
    def test_extract_counts(self) -> None:
        mod = _load_module()
        counts = mod.extract_counts({"matrix_total": 20, "matrix_evaluated": 20, "matrix_skipped": 0, "matrix_failed": 0})
        self.assertEqual(counts["total"], 20)
        self.assertEqual(counts["evaluated"], 20)
        self.assertEqual(counts["skipped"], 0)
        self.assertEqual(counts["failed"], 0)

    def test_main_passes_on_strict_green(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            out = root / "gate.json"
            report.write_text(json.dumps({"matrix_total": 20, "matrix_evaluated": 20, "matrix_skipped": 0, "matrix_failed": 0}), encoding="utf-8")
            rc = mod.main(["--report", str(report), "--output", str(out), "--expected-total", "20"])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))

    def test_main_fails_on_skipped_or_failed(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            out = root / "gate.json"
            report.write_text(json.dumps({"matrix_total": 20, "matrix_evaluated": 19, "matrix_skipped": 1, "matrix_failed": 0}), encoding="utf-8")
            rc = mod.main(["--report", str(report), "--output", str(out), "--expected-total", "20"])
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("evaluated_mismatch", reasons)
            self.assertIn("skipped_nonzero", reasons)

    def test_main_fails_when_report_has_failure_reasons_even_if_counts_green(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report = root / "report.json"
            out = root / "gate.json"
            report.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "matrix_total": 20,
                        "matrix_evaluated": 20,
                        "matrix_skipped": 0,
                        "matrix_failed": 0,
                        "failure_reasons": ["strict_source_disallowed"],
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--report", str(report), "--output", str(out), "--expected-total", "20"])
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("report_ok_false", reasons)
            self.assertIn("report_failure_reasons_nonempty", reasons)


if __name__ == "__main__":
    unittest.main()
