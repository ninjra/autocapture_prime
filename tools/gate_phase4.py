"""Gate: Phase 4 retrieval + provenance + citations checks."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


def _run_suite(module: str) -> tuple[str, dict]:
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=1)
    result = runner.run(suite)
    status = "pass"
    skip_reason = None
    if result.failures or result.errors:
        status = "fail"
    elif result.testsRun > 0 and len(result.skipped) == result.testsRun:
        status = "skip"
        skip_reason = "; ".join(reason for _test, reason in result.skipped)
    return status, {
        "name": module,
        "status": status,
        "skipped": len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skip_reason": skip_reason,
    }


def main() -> int:
    checks = [
        "tests.test_retrieval",
        "tests.test_retrieval_indexed_hits",
        "tests.test_retrieval_full_scan_guard",
        "tests.test_retrieval_golden",
        "tests.test_retrieval_timeline_refs",
        "tests.test_rrf_fusion_determinism",
        "tests.test_state_layer_golden",
        "tests.test_state_layer_evidence_compiler",
        "tests.test_state_layer_frame_evidence",
        "tests.test_state_layer_builder",
        "tests.test_state_retrieval_fallback",
        "tests.test_context_pack_formats",
        "tests.test_span_ids_stable",
        "tests.test_span_bbox_norm",
        "tests.test_vector_index_roundtrip",
        "tests.test_fts_query_returns_hits",
        "tests.test_graph_adapter_contract",
        "tests.test_answer_builder",
        "tests.test_citation_validation",
        "tests.test_citation_validator_metadata",
        "tests.test_citation_span_ref",
        "tests.test_provenance_chain",
        "tests.test_evidence_schema",
        "tests.test_entity_hashing_stable",
        "tests.test_query",
        "tests.test_query_citations_required",
        "tests.test_query_processing_status",
        "tests.test_query_ledger_entry",
        "tests.test_query_derived_records",
        "tests.test_proof_bundle_replay",
        "tests.test_verify_archive_cli",
        "tests.test_export_import_roundtrip",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase4"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase4.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
