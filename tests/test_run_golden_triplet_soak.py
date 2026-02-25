from __future__ import annotations

import json
import pathlib
from typing import Any

import tools.run_golden_triplet_soak as soak


def _resp(*, ok: bool, stdout: str = "", stderr: str = "", elapsed_ms: int = 10) -> dict[str, Any]:
    return {
        "cmd": [],
        "returncode": 0 if ok else 1,
        "elapsed_ms": int(elapsed_ms),
        "ok": bool(ok),
        "stdout": str(stdout),
        "stderr": str(stderr),
    }


def test_soak_optional_popup_with_synthetic_q40_fallback(tmp_path: pathlib.Path, monkeypatch) -> None:
    out = tmp_path / "soak.json"
    synth_matrix = tmp_path / "q40_synth_matrix.json"
    synth_matrix.write_text(json.dumps({"ok": True}), encoding="utf-8")
    synth_report = tmp_path / "report.json"
    synth_report.write_text(json.dumps({"ok": True}), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, cwd: pathlib.Path, env: dict[str, str] | None = None) -> dict[str, Any]:
        calls.append(list(cmd))
        if cmd[:2] == [str(pathlib.Path(cwd) / ".venv" / "bin" / "python"), "tools/gate_stage1_contract.py"]:
            return _resp(ok=True, stdout='{"ok": true}')
        if cmd[:2] == [str(pathlib.Path(cwd) / ".venv" / "bin" / "python"), "tools/verify_query_upstream_runtime_contract.py"]:
            return _resp(ok=False, stdout='{"ok": false}')
        if cmd[:2] == ["bash", "tools/run_popup_regression_strict.sh"]:
            return _resp(ok=False, stdout='{"ok": false}')
        if cmd[:2] == ["bash", "tools/q40.sh"]:
            return _resp(ok=False, stdout='{"ok": false}')
        if cmd[:2] == ["bash", "tools/run_q40_uia_synthetic.sh"]:
            return _resp(
                ok=True,
                stdout=json.dumps({"matrix": str(synth_matrix), "report": str(synth_report)}),
            )
        if cmd[:2] == ["bash", "tools/run_temporal_qa40_strict.sh"]:
            return _resp(ok=True, stdout='{"ok": true}')
        if "tools/gate_golden_pipeline_triplet.py" in cmd:
            raise AssertionError("composite gate should be skipped when popup strict is optional and failed")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(soak, "_run", fake_run)
    monkeypatch.setattr(soak.time, "sleep", lambda _: None)

    rc = soak.main(
        [
            "--cycles",
            "1",
            "--output",
            str(out),
            "--repo-root",
            str(pathlib.Path.cwd()),
            "--no-require-popup-strict",
            "--allow-synthetic-fallback",
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    row = payload["rows"][0]
    assert row["verify_runtime"]["soft_failed"] is True
    assert row["popup_strict"]["soft_failed"] is True
    assert row["source_tier"] == "synthetic"
    assert row["q40_strict"]["effective_ok"] is True
    assert row["q40_strict"]["fallback_used"] is True
    assert row["composite_gate"]["skipped"] is True
    assert row["composite_gate"]["reason"] == "popup_soft_failed_optional"


def test_soak_popup_required_fails_fast(tmp_path: pathlib.Path, monkeypatch) -> None:
    out = tmp_path / "soak.json"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, cwd: pathlib.Path, env: dict[str, str] | None = None) -> dict[str, Any]:
        calls.append(list(cmd))
        if cmd[:2] == [str(pathlib.Path(cwd) / ".venv" / "bin" / "python"), "tools/gate_stage1_contract.py"]:
            return _resp(ok=True, stdout='{"ok": true}')
        if cmd[:2] == [str(pathlib.Path(cwd) / ".venv" / "bin" / "python"), "tools/verify_query_upstream_runtime_contract.py"]:
            return _resp(ok=True, stdout='{"ok": true}')
        if cmd[:2] == ["bash", "tools/run_popup_regression_strict.sh"]:
            return _resp(ok=False, stdout='{"ok": false}')
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(soak, "_run", fake_run)
    monkeypatch.setattr(soak.time, "sleep", lambda _: None)

    rc = soak.main(
        [
            "--cycles",
            "1",
            "--output",
            str(out),
            "--repo-root",
            str(pathlib.Path.cwd()),
            "--require-popup-strict",
            "--stop-on-fail",
        ]
    )
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["failure_reason"] == "cycle_1:popup_strict_failed"
    assert payload["cycles_completed"] == 1
    assert not any(cmd[:2] == ["bash", "tools/q40.sh"] for cmd in calls)


def test_soak_stage1_required_fails_fast_before_runtime_checks(tmp_path: pathlib.Path, monkeypatch) -> None:
    out = tmp_path / "soak.json"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, cwd: pathlib.Path, env: dict[str, str] | None = None) -> dict[str, Any]:
        calls.append(list(cmd))
        if cmd[:2] == [str(pathlib.Path(cwd) / ".venv" / "bin" / "python"), "tools/gate_stage1_contract.py"]:
            return _resp(ok=False, stdout='{"ok": false}')
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(soak, "_run", fake_run)
    monkeypatch.setattr(soak.time, "sleep", lambda _: None)

    rc = soak.main(
        [
            "--cycles",
            "1",
            "--output",
            str(out),
            "--repo-root",
            str(pathlib.Path.cwd()),
            "--require-stage1-contract",
            "--stop-on-fail",
        ]
    )
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["failure_reason"] == "cycle_1:stage1_contract_failed"
    assert payload["cycles_completed"] == 1
    row = payload["rows"][0]
    assert row["stage1_contract"]["ok"] is False
    assert not any(
        cmd[:2] == [str(pathlib.Path.cwd() / ".venv" / "bin" / "python"), "tools/verify_query_upstream_runtime_contract.py"]
        for cmd in calls
    )
