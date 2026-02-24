from __future__ import annotations

import importlib.util
import pathlib
import sys
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/release_gate.py")
    spec = importlib.util.spec_from_file_location("release_gate_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_find_non_pass_markers_detects_skip_and_warn() -> None:
    mod = _load_module()
    payload = {"ok": True, "checks": [{"status": "pass"}, {"status": "skip"}], "warnings": ["x"]}
    issues = mod._find_non_pass_markers(payload)
    assert any("skip" in issue for issue in issues)
    assert any("warnings" in issue for issue in issues)


def test_find_non_pass_markers_accepts_all_pass() -> None:
    mod = _load_module()
    payload = {"ok": True, "checks": [{"status": "pass"}, {"status": "ok"}]}
    issues = mod._find_non_pass_markers(payload)
    assert issues == []


def test_find_non_pass_markers_detects_matrix_semantic_violations() -> None:
    mod = _load_module()
    payload = {"ok": True, "matrix_total": 40, "matrix_evaluated": 0, "matrix_skipped": 40, "matrix_failed": 0}
    issues = mod._find_non_pass_markers(payload)
    assert any("matrix_evaluated=0" in issue for issue in issues)
    assert any("matrix_skipped=nonzero" in issue for issue in issues)


def test_find_non_pass_markers_accepts_strict_matrix_green() -> None:
    mod = _load_module()
    payload = {"ok": True, "matrix_total": 40, "matrix_evaluated": 40, "matrix_skipped": 0, "matrix_failed": 0}
    issues = mod._find_non_pass_markers(payload)
    assert issues == []


def test_default_manifest_includes_required_release_steps() -> None:
    mod = _load_module()
    steps = mod._default_manifest(sys.executable)
    ids = {step.id for step in steps}
    assert "gate_phase0" in ids
    assert "gate_phase8" in ids
    assert "gate_promptops_policy" in ids
    assert "gate_promptops_perf" in ids
    assert "gate_screen_schema" in ids
    assert "gate_ledger" in ids
    assert "gate_deps_lock" in ids
    assert "gate_static" in ids
    assert "gate_vuln" in ids
    assert "gate_doctor" in ids
    assert "gate_full_repo_miss_matrix" in ids
    assert "gate_acceptance_coverage" in ids
    assert "gate_queryability" in ids
    assert "validate_blueprint_spec" in ids
    assert "run_mod021_low_resource" in ids
    assert "popup_go_no_go" in ids
    assert "run_real_corpus_readiness" in ids
    assert "gate_real_corpus_strict" in ids


def test_default_manifest_can_disable_real_corpus_steps() -> None:
    mod = _load_module()
    with mock.patch.dict(mod.os.environ, {"REAL_CORPUS_STRICT_DISABLED": "1"}, clear=False):
        steps = mod._default_manifest(sys.executable)
    ids = {step.id for step in steps}
    assert "run_real_corpus_readiness" not in ids
    assert "gate_real_corpus_strict" not in ids


def test_default_manifest_can_disable_popup_go_no_go() -> None:
    mod = _load_module()
    with mock.patch.dict(mod.os.environ, {"POPUP_GO_NO_GO_DISABLED": "1"}, clear=False):
        steps = mod._default_manifest(sys.executable)
    ids = {step.id for step in steps}
    assert "popup_go_no_go" not in ids


def test_run_release_gate_honors_max_steps(tmp_path: pathlib.Path) -> None:
    mod = _load_module()

    class _FakeStep:
        def __init__(self, id: str):
            self.id = id
            self.cmd = ["echo", id]
            self.artifact = None

    fake_steps = [_FakeStep("a"), _FakeStep("b"), _FakeStep("c")]
    with (
        mock.patch.object(mod, "_default_manifest", return_value=fake_steps),
        mock.patch.object(
            mod,
            "_run_step",
            side_effect=[
                {"id": "a", "ok": True, "returncode": 0, "issues": []},
                {"id": "b", "ok": True, "returncode": 0, "issues": []},
                {"id": "c", "ok": True, "returncode": 0, "issues": []},
            ],
        ),
    ):
        payload = mod.run_release_gate(root=tmp_path, strict_status=True, max_steps=2)
    assert payload["ok"] is True
    assert payload["steps_planned_this_run"] == 2
    assert payload["steps_executed"] == 2


def test_run_release_gate_honors_start_step(tmp_path: pathlib.Path) -> None:
    mod = _load_module()

    class _FakeStep:
        def __init__(self, id: str):
            self.id = id
            self.cmd = ["echo", id]
            self.artifact = None

    fake_steps = [_FakeStep("a"), _FakeStep("b"), _FakeStep("c")]
    with (
        mock.patch.object(mod, "_default_manifest", return_value=fake_steps),
        mock.patch.object(
            mod,
            "_run_step",
            side_effect=[
                {"id": "b", "ok": True, "returncode": 0, "issues": []},
                {"id": "c", "ok": True, "returncode": 0, "issues": []},
            ],
        ),
    ):
        payload = mod.run_release_gate(root=tmp_path, strict_status=True, start_step=2)
    assert payload["ok"] is True
    assert payload["start_step"] == 2
    assert payload["steps_planned_this_run"] == 2
    assert payload["steps_executed"] == 2
