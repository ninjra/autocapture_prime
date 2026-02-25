from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


def _load_module():
    path = pathlib.Path("tools/release_quickcheck.py")
    spec = importlib.util.spec_from_file_location("release_quickcheck_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_quickcheck_collects_status_counts_and_top_reasons(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    root = tmp_path
    _write_json(root / "artifacts/release/release_gate_latest.json", {"ok": True})
    _write_json(
        root / "artifacts/query_acceptance/popup_regression_latest.json",
        {"ok": False, "sample_count": 10, "accepted_count": 0, "failed_count": 10},
    )
    _write_json(
        root / "artifacts/query_acceptance/popup_regression_misses_latest.json",
        {"failure_reason_counts": {"state_not_ok": 10}},
    )
    _write_json(
        root / "artifacts/advanced10/q40_matrix_latest.json",
        {"ok": False, "matrix_total": 40, "matrix_evaluated": 40, "matrix_skipped": 0, "matrix_failed": 3, "failure_reasons": ["matrix_failed_nonzero"]},
    )
    _write_json(
        root / "artifacts/temporal40/temporal40_gate_latest.json",
        {"ok": True, "counts": {"evaluated": 40, "skipped": 0, "failed": 0}},
    )
    _write_json(
        root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json",
        {
            "ok": False,
            "matrix_total": 20,
            "matrix_evaluated": 20,
            "matrix_skipped": 0,
            "matrix_failed": 4,
            "strict_failure_causes": {"citation_invalid": 7, "retrieval_miss": 0},
            "strict_failure_cause_counts": {"citation_invalid": 7, "retrieval_miss": 0},
        },
    )
    _write_json(
        root / "artifacts/lineage/20260225T100000Z/stage1_stage2_lineage_queryability.json",
        {"summary": {"frames_total": 100, "frames_queryable": 80, "frames_blocked": 20, "lineage_complete": 75, "lineage_incomplete": 25}},
    )

    out = mod.build_quickcheck(root=root)
    assert out["ok"] is False
    assert out["statuses"]["release_gate_ok"] is True
    assert out["statuses"]["popup_strict_ok"] is False
    assert out["statuses"]["q40_strict_ok"] is False
    assert out["counts"]["q40"]["matrix_failed"] == 3
    assert out["stage_coverage"]["frames_total"] == 100
    assert out["stage_coverage"]["frames_queryable"] == 80
    assert "state_not_ok" in out["top_failure_reasons"]
    assert "matrix_failed_nonzero" in out["top_failure_reasons"]
    assert "citation_invalid" in out["top_failure_reasons"]
    assert "retrieval_miss" not in out["top_failure_reasons"]


def test_build_quickcheck_requires_real_q40_source_tier_for_q40_ok(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    root = tmp_path
    _write_json(root / "artifacts/release/release_gate_latest.json", {"ok": True})
    _write_json(root / "artifacts/query_acceptance/popup_regression_latest.json", {"ok": True, "sample_count": 10, "accepted_count": 10, "failed_count": 0})
    _write_json(root / "artifacts/advanced10/q40_matrix_latest.json", {"ok": True, "matrix_total": 40, "matrix_evaluated": 40, "matrix_skipped": 0, "matrix_failed": 0, "source_tier": "synthetic"})
    _write_json(root / "artifacts/temporal40/temporal40_gate_latest.json", {"ok": True, "counts": {"evaluated": 40, "skipped": 0, "failed": 0}})
    _write_json(
        root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json",
        {"ok": True, "matrix_total": 20, "matrix_evaluated": 20, "matrix_skipped": 0, "matrix_failed": 0, "source_tier": "real"},
    )
    out = mod.build_quickcheck(root=root)
    assert out["statuses"]["q40_strict_ok"] is False
    assert out["counts"]["q40"]["source_tier"] == "synthetic"
    assert "q40.source_tier_not_real" in out["top_failure_reasons"]


def test_build_quickcheck_lineage_fallback_reads_root_keys(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    root = tmp_path
    _write_json(root / "artifacts/release/release_gate_latest.json", {"ok": True})
    _write_json(root / "artifacts/query_acceptance/popup_regression_latest.json", {"ok": True, "sample_count": 10, "accepted_count": 10, "failed_count": 0})
    _write_json(root / "artifacts/advanced10/q40_matrix_latest.json", {"ok": True, "source_tier": "real"})
    _write_json(root / "artifacts/temporal40/temporal40_gate_latest.json", {"ok": True, "counts": {"evaluated": 40, "skipped": 0, "failed": 0}})
    _write_json(root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json", {"ok": True, "source_tier": "real"})
    _write_json(
        root / "artifacts/lineage/20260225T100000Z/stage1_stage2_lineage_queryability.json",
        {"summary": {"frames_total": 100, "frames_queryable": 90, "frames_blocked": 10}, "lineage_complete": 88, "lineage_incomplete": 12},
    )
    out = mod.build_quickcheck(root=root)
    assert out["stage_coverage"]["frames_total"] == 100
    assert out["stage_coverage"]["lineage_complete"] == 88
    assert out["stage_coverage"]["lineage_incomplete"] == 12


def test_build_quickcheck_lineage_fallback_derives_from_queryable_counts(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    root = tmp_path
    _write_json(root / "artifacts/release/release_gate_latest.json", {"ok": True})
    _write_json(root / "artifacts/query_acceptance/popup_regression_latest.json", {"ok": True, "sample_count": 10, "accepted_count": 10, "failed_count": 0})
    _write_json(root / "artifacts/advanced10/q40_matrix_latest.json", {"ok": True, "source_tier": "real"})
    _write_json(root / "artifacts/temporal40/temporal40_gate_latest.json", {"ok": True, "counts": {"evaluated": 40, "skipped": 0, "failed": 0}})
    _write_json(root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json", {"ok": True, "source_tier": "real"})
    _write_json(
        root / "artifacts/lineage/20260225T100000Z/stage1_stage2_lineage_queryability.json",
        {"summary": {"frames_total": 180, "frames_queryable": 171, "frames_blocked": 9}},
    )
    out = mod.build_quickcheck(root=root)
    assert out["stage_coverage"]["frames_total"] == 180
    assert out["stage_coverage"]["frames_queryable"] == 171
    assert out["stage_coverage"]["lineage_complete"] == 171
    assert out["stage_coverage"]["lineage_incomplete"] == 9


def test_build_quickcheck_parses_nested_strict_failure_causes_without_wrapper_keys(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    root = tmp_path
    _write_json(root / "artifacts/release/release_gate_latest.json", {"ok": False})
    _write_json(root / "artifacts/query_acceptance/popup_regression_latest.json", {"ok": True, "sample_count": 10, "accepted_count": 10, "failed_count": 0})
    _write_json(root / "artifacts/advanced10/q40_matrix_latest.json", {"ok": True, "source_tier": "real"})
    _write_json(root / "artifacts/temporal40/temporal40_gate_latest.json", {"ok": True, "counts": {"evaluated": 40, "skipped": 0, "failed": 0}})
    _write_json(
        root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json",
        {
            "ok": False,
            "source_tier": "real",
            "strict_failure_causes": {
                "by_case": [{"id": "Q1", "cause": "retrieval_miss"}],
                "counts": {"retrieval_miss": 1, "citation_invalid": 0},
            },
        },
    )
    out = mod.build_quickcheck(root=root)
    assert "retrieval_miss" in out["top_failure_reasons"]
    assert "by_case" not in out["top_failure_reasons"]
    assert "counts" not in out["top_failure_reasons"]


def test_build_quickcheck_handles_missing_artifacts(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    out = mod.build_quickcheck(root=tmp_path)
    assert out["ok"] is False
    assert len(out["missing_artifacts"]) >= 5
    assert out["statuses"]["release_gate_ok"] is False
    assert out["counts"]["q40"]["matrix_total"] == 0


def test_main_strict_exit_nonzero_when_not_ok(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    _write_json(tmp_path / "artifacts/release/release_gate_latest.json", {"ok": False, "failure_reasons": ["x"]})
    _write_json(tmp_path / "artifacts/query_acceptance/popup_regression_latest.json", {"ok": False, "sample_count": 10, "accepted_count": 0, "failed_count": 10})
    _write_json(tmp_path / "artifacts/advanced10/q40_matrix_latest.json", {"ok": False})
    _write_json(tmp_path / "artifacts/temporal40/temporal40_gate_latest.json", {"ok": False, "counts": {"evaluated": 0, "skipped": 0, "failed": 0}})
    _write_json(tmp_path / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json", {"ok": False, "source_tier": "real"})
    rc = mod.main(["--repo-root", str(tmp_path), "--strict-exit"])
    assert rc == 1


def test_build_quickcheck_requires_real_real_corpus_source_tier(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    root = tmp_path
    _write_json(root / "artifacts/release/release_gate_latest.json", {"ok": True})
    _write_json(root / "artifacts/query_acceptance/popup_regression_latest.json", {"ok": True, "sample_count": 10, "accepted_count": 10, "failed_count": 0})
    _write_json(root / "artifacts/advanced10/q40_matrix_latest.json", {"ok": True, "source_tier": "real"})
    _write_json(root / "artifacts/temporal40/temporal40_gate_latest.json", {"ok": True, "counts": {"evaluated": 40, "skipped": 0, "failed": 0}})
    _write_json(root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json", {"ok": True, "source_tier": "synthetic"})
    out = mod.build_quickcheck(root=root)
    assert out["statuses"]["real_corpus_strict_ok"] is False
    assert out["counts"]["real_corpus"]["source_tier"] == "synthetic"
    assert "real_corpus.source_tier_not_real" in out["top_failure_reasons"]
