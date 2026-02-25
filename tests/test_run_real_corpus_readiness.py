from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/run_real_corpus_readiness.py")
    spec = importlib.util.spec_from_file_location("run_real_corpus_readiness_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mk_row(
    *,
    case_id: str,
    passed: bool = True,
    skipped: bool = False,
    answer_state: str = "ok",
    citation_count: int = 1,
) -> dict[str, object]:
    return {
        "id": case_id,
        "ok": bool(passed),
        "skipped": bool(skipped),
        "query_run_id": f"run_{case_id}",
        "summary": "ok summary",
        "answer_state": answer_state,
        "stage_ms": {"total": 100.0},
        "query_contract_metrics": {
            "query_extractor_launch_total": 0,
            "query_schedule_extract_requests_total": 0,
            "query_raw_media_reads_total": 0,
        },
        "expected_eval": {"evaluated": not skipped, "passed": bool(passed)},
        "providers": [
            {
                "provider_id": "builtin.observation.graph",
                "citation_count": int(citation_count),
                "contribution_bp": 10000 if passed else 0,
            }
        ],
    }


class RealCorpusReadinessTests(unittest.TestCase):
    def test_main_passes_when_strict_contract_is_green(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 2,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]},
                                {"id": "Q2", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]},
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(json.dumps({"rows": [_mk_row(case_id="Q1"), _mk_row(case_id="Q2")]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": [_mk_row(case_id="GQ1"), _mk_row(case_id="GQ2")]}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))
            self.assertEqual(int(payload.get("matrix_total", 0)), 2)
            self.assertEqual(int(payload.get("matrix_evaluated", 0)), 2)
            self.assertEqual(int(payload.get("matrix_skipped", 0)), 0)
            self.assertEqual(int(payload.get("matrix_failed", 0)), 0)
            self.assertEqual(str(payload.get("source_tier") or ""), "real")
            query_contract = payload.get("query_contract", {}) if isinstance(payload.get("query_contract", {}), dict) else {}
            self.assertEqual(int(query_contract.get("query_extractor_launch_total", -1)), 0)
            self.assertEqual(int(query_contract.get("query_schedule_extract_requests_total", -1)), 0)
            self.assertEqual(int(query_contract.get("query_raw_media_reads_total", -1)), 0)
            self.assertLessEqual(float(query_contract.get("query_latency_p95_ms", 10_000) or 10_000), 1500.0)
            coverage_md = payload.get("queryability_coverage_md")
            self.assertTrue(isinstance(coverage_md, str) and coverage_md.strip())
            self.assertTrue(pathlib.Path(str(coverage_md)).exists())
            latest_md = payload.get("latest_report_md")
            self.assertTrue(isinstance(latest_md, str) and latest_md.strip())
            self.assertTrue(pathlib.Path(str(latest_md)).exists())

    def test_main_fails_on_missing_citations_for_strict_case(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(json.dumps({"rows": [_mk_row(case_id="Q1", citation_count=0)]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": []}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("ok", True)))
            self.assertIn("strict_matrix_failed_nonzero", set(payload.get("failure_reasons", [])))

    def test_main_accepts_claim_level_citations_when_provider_count_is_zero(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            row = _mk_row(case_id="Q1", citation_count=0)
            row["answer"] = {
                "claims": [
                    {
                        "citations": [
                            {
                                "evidence_id": "rec_123",
                                "locator": {"kind": "metadata.record"},
                            }
                        ]
                    }
                ]
            }
            adv.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": []}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))
            self.assertEqual(int(payload.get("matrix_failed", 0)), 0)

    def test_generic_failures_are_informational_only(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(json.dumps({"rows": [_mk_row(case_id="Q1")]}), encoding="utf-8")
            gen.write_text(
                json.dumps(
                    {
                        "rows": [
                            _mk_row(case_id="GQ1", passed=False),
                            _mk_row(case_id="GQ2", skipped=True),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("ok", False)))
            generic = payload.get("generic20", {})
            self.assertEqual(int(generic.get("failed", 0)), 1)
            self.assertEqual(int(generic.get("skipped", 0)), 1)

    def test_source_policy_blocks_synthetic_source_paths(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "source_policy": {
                                "require_real_corpus": True,
                                "disallowed_substrings": ["/artifacts/single_image_runs/"],
                            },
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(
                json.dumps(
                    {
                        "source_report": "/tmp/artifacts/single_image_runs/fake/report.json",
                        "rows": [_mk_row(case_id="Q1")],
                    }
                ),
                encoding="utf-8",
            )
            gen.write_text(json.dumps({"rows": []}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("strict_source_disallowed", reasons)

    def test_source_policy_blocks_relative_synthetic_source_paths(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "source_policy": {
                                "require_real_corpus": True,
                                "disallowed_substrings": ["/artifacts/single_image_runs/"],
                            },
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(
                json.dumps(
                    {
                        "source_report": "artifacts/single_image_runs/fake/report.json",
                        "rows": [_mk_row(case_id="Q1")],
                    }
                ),
                encoding="utf-8",
            )
            gen.write_text(json.dumps({"rows": []}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("strict_source_disallowed", reasons)

    def test_source_policy_requires_nonempty_source_paths(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "source_policy": {
                                "require_real_corpus": True,
                                "disallowed_substrings": ["/artifacts/single_image_runs/"],
                            },
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(json.dumps({"source_report": "", "rows": [_mk_row(case_id="Q1")]}), encoding="utf-8")
            gen.write_text(json.dumps({"source_report": "", "rows": []}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("strict_source_missing", reasons)

    def test_source_policy_blocks_non_real_source_tier(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "source_policy": {"require_real_corpus": True},
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(json.dumps({"source_report": str(root / "adv.json"), "rows": [_mk_row(case_id="Q1")]}), encoding="utf-8")
            gen.write_text(json.dumps({"source_report": str(root / "gen.json"), "rows": []}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--source-tier",
                    "synthetic",
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("source_tier") or ""), "synthetic")
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("strict_source_tier_disallowed", reasons)

    def test_main_fails_when_query_contract_metrics_violate_read_only(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            bad = _mk_row(case_id="Q1")
            bad["query_contract_metrics"] = {
                "query_extractor_launch_total": 0,
                "query_schedule_extract_requests_total": 1,
                "query_raw_media_reads_total": 0,
            }
            adv.write_text(json.dumps({"rows": [bad]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": [_mk_row(case_id="GQ1")]}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("query_contract_schedule_requests_nonzero", reasons)

    def test_main_fails_when_query_latency_p95_exceeds_budget(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            slow = _mk_row(case_id="Q1")
            slow["stage_ms"] = {"total": 4000.0}
            adv.write_text(json.dumps({"rows": [slow]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": [_mk_row(case_id="GQ1")]}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("query_contract_latency_p95_exceeded", reasons)

    def test_main_emits_strict_failure_cause_categories(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 3,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]},
                                {"id": "Q2", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]},
                                {"id": "Q3", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]},
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            q1 = _mk_row(case_id="Q1", citation_count=0)
            q2 = _mk_row(case_id="Q2", passed=False, answer_state="error")
            q3 = _mk_row(case_id="Q3")
            q3["summary"] = "indeterminate due to missing path"
            adv.write_text(json.dumps({"rows": [q1, q2, q3]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": [_mk_row(case_id="GQ1")]}), encoding="utf-8")
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            cause_counts = payload.get("strict_failure_cause_counts", {})
            self.assertEqual(int(cause_counts.get("citation_invalid", 0)), 1)
            self.assertEqual(int(cause_counts.get("upstream_unreachable", 0)), 1)
            self.assertEqual(int(cause_counts.get("retrieval_miss", 0)), 1)
            causes = payload.get("strict_failure_causes", {})
            by_case = causes.get("by_case", []) if isinstance(causes.get("by_case", []), list) else []
            self.assertTrue(bool(by_case))
            case_q1 = next((row for row in by_case if str(row.get("id") or "") == "Q1"), {})
            self.assertEqual(str(case_q1.get("cause") or ""), "citation_invalid")
            self.assertIn("citation_linkage", case_q1)
            linkage = case_q1.get("citation_linkage", {}) if isinstance(case_q1.get("citation_linkage", {}), dict) else {}
            issues = set(str(x) for x in (linkage.get("issues") or []))
            self.assertIn("providers_claims_without_citations", issues)
            providers = case_q1.get("provider_diagnostics", [])
            self.assertTrue(isinstance(providers, list) and bool(providers))

    def test_main_fails_when_queryability_ratio_below_threshold(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = root / "contract.json"
            adv = root / "advanced.json"
            gen = root / "generic.json"
            lineage = root / "lineage.json"
            out = root / "strict_matrix.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema": "autocapture.real_corpus_expected_answers.v1",
                        "strict": {
                            "expected_total": 1,
                            "cases": [
                                {"id": "Q1", "suite": "advanced20", "allow_indeterminate": False, "require_citations": True, "allowed_answer_states": ["ok"]}
                            ],
                        },
                        "generic_policy": {"suite": "generic20", "blocking": False},
                    }
                ),
                encoding="utf-8",
            )
            adv.write_text(json.dumps({"rows": [_mk_row(case_id="Q1")]}), encoding="utf-8")
            gen.write_text(json.dumps({"rows": [_mk_row(case_id="GQ1")]}), encoding="utf-8")
            lineage.write_text(
                json.dumps({"summary": {"frames_total": 100, "frames_queryable": 50}}),
                encoding="utf-8",
            )
            rc = mod.main(
                [
                    "--contract",
                    str(contract),
                    "--advanced-json",
                    str(adv),
                    "--generic-json",
                    str(gen),
                    "--lineage-json",
                    str(lineage),
                    "--min-queryable-ratio",
                    "0.95",
                    "--out",
                    str(out),
                    "--latest-report-md",
                    str(root / "latest.md"),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("queryability_slo_ratio_below_threshold", reasons)
            qslo = payload.get("queryability_slo", {}) if isinstance(payload.get("queryability_slo", {}), dict) else {}
            self.assertTrue(bool(qslo.get("enabled", False)))
            self.assertEqual(int(qslo.get("frames_total", 0) or 0), 100)
            self.assertEqual(int(qslo.get("frames_queryable", 0) or 0), 50)
            self.assertAlmostEqual(float(qslo.get("required_min_ratio", 0.0) or 0.0), 0.95, places=6)


if __name__ == "__main__":
    unittest.main()
