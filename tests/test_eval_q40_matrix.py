from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/eval_q40_matrix.py")
    spec = importlib.util.spec_from_file_location("eval_q40_matrix_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EvalQ40MatrixTests(unittest.TestCase):
    def test_matrix_counts_skipped_without_failing(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_path = root / "advanced20.json"
            gen_path = root / "generic20.json"
            out_path = root / "out.json"
            adv_path.write_text(
                json.dumps(
                    {
                        "evaluated_total": 1,
                        "evaluated_passed": 1,
                        "evaluated_failed": 0,
                        "rows_skipped": 1,
                        "rows": [
                            {"id": "Q1", "skipped": True, "expected_eval": {"evaluated": False, "passed": None, "skipped": True}},
                            {"id": "Q2", "expected_eval": {"evaluated": True, "passed": True}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gen_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"id": "G1", "skipped": True},
                            {
                                "id": "G2",
                                "ok": True,
                                "query_run_id": "qr-1",
                                "summary": "ok",
                                "answer_state": "ok",
                                "expected_eval": {"passed": True},
                                "providers": [{"provider_id": "builtin.observation.graph", "contribution_bp": 10000}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--advanced-json", str(adv_path), "--generic-json", str(gen_path), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertEqual(str(payload.get("source_tier") or ""), "real")
            self.assertEqual(payload.get("matrix_total"), 4)
            self.assertEqual(payload.get("matrix_evaluated"), 2)
            self.assertEqual(payload.get("matrix_passed"), 2)
            self.assertEqual(payload.get("matrix_failed"), 0)
            self.assertEqual(payload.get("matrix_skipped"), 2)

    def test_can_write_synthetic_source_tier(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_path = root / "advanced20.json"
            gen_path = root / "generic20.json"
            out_path = root / "out.json"
            adv_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"id": "Q1", "expected_eval": {"evaluated": True, "passed": True}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gen_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "id": "G1",
                                "ok": True,
                                "query_run_id": "qr-1",
                                "summary": "ok",
                                "answer_state": "ok",
                                "expected_eval": {"passed": True},
                                "providers": [{"provider_id": "builtin.observation.graph", "contribution_bp": 10000}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(
                [
                    "--advanced-json",
                    str(adv_path),
                    "--generic-json",
                    str(gen_path),
                    "--out",
                    str(out_path),
                    "--source-tier",
                    "synthetic",
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("source_tier") or ""), "synthetic")

    def test_strict_mode_fails_when_any_case_skipped(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_path = root / "advanced20.json"
            gen_path = root / "generic20.json"
            out_path = root / "out.json"
            adv_path.write_text(
                json.dumps(
                    {
                        "evaluated_total": 1,
                        "evaluated_passed": 1,
                        "evaluated_failed": 0,
                        "rows_skipped": 1,
                        "rows": [
                            {"id": "Q1", "skipped": True, "expected_eval": {"evaluated": False, "passed": None, "skipped": True}},
                            {"id": "Q2", "expected_eval": {"evaluated": True, "passed": True}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gen_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"id": "G1", "skipped": True},
                            {
                                "id": "G2",
                                "ok": True,
                                "query_run_id": "qr-1",
                                "summary": "ok",
                                "answer_state": "ok",
                                "expected_eval": {"passed": True},
                                "providers": [{"provider_id": "builtin.observation.graph", "contribution_bp": 10000}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--advanced-json", str(adv_path), "--generic-json", str(gen_path), "--out", str(out_path), "--strict"])
            self.assertEqual(rc, 1)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            self.assertIn("strict_matrix_skipped_nonzero", payload.get("failure_reasons", []))

    def test_all_skipped_fails_when_matrix_evaluated_is_zero(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_path = root / "advanced20.json"
            gen_path = root / "generic20.json"
            out_path = root / "out.json"
            adv_path.write_text(
                json.dumps(
                    {
                        "evaluated_total": 0,
                        "evaluated_passed": 0,
                        "evaluated_failed": 0,
                        "rows_skipped": 2,
                        "rows": [
                            {"id": "Q1", "skipped": True, "expected_eval": {"evaluated": False, "passed": None, "skipped": True}},
                            {"id": "Q2", "skipped": True, "expected_eval": {"evaluated": False, "passed": None, "skipped": True}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gen_path.write_text(json.dumps({"rows": [{"id": "G1", "skipped": True}, {"id": "G2", "skipped": True}]}), encoding="utf-8")
            rc = mod.main(["--advanced-json", str(adv_path), "--generic-json", str(gen_path), "--out", str(out_path)])
            self.assertEqual(rc, 1)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            self.assertEqual(int(payload.get("matrix_evaluated", -1)), 0)
            self.assertIn("matrix_evaluated_zero", payload.get("failure_reasons", []))

    def test_strict_mode_fails_on_provenance_mismatch(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_path = root / "advanced20.json"
            gen_path = root / "generic20.json"
            out_path = root / "out.json"
            adv_path.write_text(
                json.dumps(
                    {
                        "source_report": "/tmp/report_a.json",
                        "source_report_sha256": "a" * 64,
                        "rows": [
                            {
                                "id": "Q1",
                                "expected_eval": {"evaluated": True, "passed": True},
                                "source_report": "/tmp/report_a.json",
                                "source_report_sha256": "a" * 64,
                                "source_report_run_id": "run-a",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gen_path.write_text(
                json.dumps(
                    {
                        "source_report": "/tmp/report_b.json",
                        "source_report_sha256": "b" * 64,
                        "rows": [
                            {
                                "id": "G1",
                                "ok": True,
                                "query_run_id": "qr-1",
                                "summary": "ok",
                                "answer_state": "ok",
                                "expected_eval": {"passed": True},
                                "providers": [{"provider_id": "builtin.observation.graph", "contribution_bp": 10000}],
                                "source_report": "/tmp/report_b.json",
                                "source_report_sha256": "b" * 64,
                                "source_report_run_id": "run-b",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--advanced-json", str(adv_path), "--generic-json", str(gen_path), "--out", str(out_path), "--strict"])
            self.assertEqual(rc, 1)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("strict_provenance_mismatch", payload.get("failure_reasons", []))

    def test_strict_mode_passes_with_matching_provenance(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            adv_path = root / "advanced20.json"
            gen_path = root / "generic20.json"
            out_path = root / "out.json"
            common_sha = "c" * 64
            adv_path.write_text(
                json.dumps(
                    {
                        "source_report": "/tmp/report_same.json",
                        "source_report_sha256": common_sha,
                        "rows": [
                            {
                                "id": "Q1",
                                "expected_eval": {"evaluated": True, "passed": True},
                                "source_report": "/tmp/report_same.json",
                                "source_report_sha256": common_sha,
                                "source_report_run_id": "run-same",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gen_path.write_text(
                json.dumps(
                    {
                        "source_report": "/tmp/report_same.json",
                        "source_report_sha256": common_sha,
                        "rows": [
                            {
                                "id": "G1",
                                "ok": True,
                                "query_run_id": "qr-1",
                                "summary": "ok",
                                "answer_state": "ok",
                                "expected_eval": {"passed": True},
                                "providers": [{"provider_id": "builtin.observation.graph", "contribution_bp": 10000}],
                                "source_report": "/tmp/report_same.json",
                                "source_report_sha256": common_sha,
                                "source_report_run_id": "run-same",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--advanced-json", str(adv_path), "--generic-json", str(gen_path), "--out", str(out_path), "--strict"])
            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))

    def test_generic_contract_fails_on_disallowed_answer_provider_activity(self) -> None:
        mod = _load_module()
        row = {
            "id": "G1",
            "ok": True,
            "query_run_id": "qr-1",
            "summary": "ok",
            "answer_state": "ok",
            "expected_eval": {"passed": True},
            "providers": [
                {"provider_id": "builtin.observation.graph", "contribution_bp": 10000},
                {"provider_id": "hard_vlm.direct", "claim_count": 1, "citation_count": 1, "contribution_bp": 0},
            ],
        }
        ok, errors = mod._generic_contract_check(row)
        self.assertFalse(ok)
        self.assertIn("disallowed_answer_provider_activity", errors)


if __name__ == "__main__":
    unittest.main()
