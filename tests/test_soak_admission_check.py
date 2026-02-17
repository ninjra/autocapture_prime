from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


def _load_module():
    path = pathlib.Path("tools/soak/admission_check.py")
    spec = importlib.util.spec_from_file_location("soak_admission_check_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_advanced(path: pathlib.Path, *, passed: int, failed: int, total: int = 20, citation_count: int = 1) -> None:
    rows = []
    for _ in range(total):
        rows.append(
            {
                "providers": [
                    {"provider_id": "builtin.observation.graph", "citation_count": citation_count},
                ]
            }
        )
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "evaluated_total": total,
                "evaluated_passed": passed,
                "evaluated_failed": failed,
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )


def test_precheck_passes_with_release_gate_and_three_runs(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"ok": True}), encoding="utf-8")
    for idx in range(3):
        _write_advanced(tmp_path / f"advanced20_{idx}.json", passed=20, failed=0)
    payload = mod._precheck(
        release_report=release,
        advanced_glob=str(tmp_path / "advanced20_*.json"),
        require_runs=3,
        citation_min_ratio=0.9,
    )
    assert payload["ok"] is True


def test_precheck_fails_when_not_enough_good_runs(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"ok": True}), encoding="utf-8")
    _write_advanced(tmp_path / "advanced20_a.json", passed=20, failed=0)
    _write_advanced(tmp_path / "advanced20_b.json", passed=19, failed=1)
    payload = mod._precheck(
        release_report=release,
        advanced_glob=str(tmp_path / "advanced20_*.json"),
        require_runs=3,
        citation_min_ratio=0.9,
    )
    assert payload["ok"] is False


def test_postcheck_fails_when_soak_summary_violates_limits(tmp_path: pathlib.Path) -> None:
    mod = _load_module()
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"ok": False, "elapsed_s": 120, "failed": 1, "blocked_vllm": 2}), encoding="utf-8")
    payload = mod._postcheck(
        soak_summary=summary,
        min_elapsed_s=1000,
        max_failed_attempts=0,
        max_blocked_vllm=0,
    )
    assert payload["ok"] is False
