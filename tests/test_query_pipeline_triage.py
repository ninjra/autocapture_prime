from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from tools import query_pipeline_triage as mod


def test_release_gate_popup_status_extracts_step_flags(tmp_path: Path) -> None:
    report = tmp_path / "release.json"
    report.write_text(
        json.dumps(
            {
                "ok": False,
                "failed_step": "popup_go_no_go",
                "steps": [
                    {"id": "popup_go_no_go", "ok": False},
                    {"id": "gate_queryability", "ok": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    out = mod._release_gate_popup_status(report)  # noqa: SLF001
    assert out["ok"] is False
    assert out["popup_go_no_go_ok"] is False
    assert out["gate_queryability_ok"] is True
    assert str(out["failed_step"] or "") == "popup_go_no_go"


def test_run_stage1_audit_timeout_returns_fail_open(monkeypatch: object, tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    db.write_text("", encoding="utf-8")
    derived = tmp_path / "stage1_derived.db"
    derived.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_load_stage1_audit_module",
        lambda: SimpleNamespace(_resolve_db_path=lambda _db: (db, "explicit")),
    )

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["audit"], timeout=1)

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    monkeypatch.setattr(mod, "_load_gate_queryability_module", lambda: (_ for _ in ()).throw(RuntimeError("no_gate")))
    payload = mod._run_stage1_audit(  # noqa: SLF001
        db=db,
        derived_db=derived,
        gap_seconds=120,
        sample_limit=20,
        frame_limit=100,
        timeout_s=1.0,
    )
    assert payload["ok"] is False
    assert str(payload["error"] or "") == "stage1_audit_timeout"
    assert str(payload["db_resolved"] or "") == str(db)
    assert str(payload["derived_db_resolved"] or "") == str(derived)


def test_run_stage1_audit_timeout_uses_fast_queryability_fallback(monkeypatch: object, tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    db.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "_load_stage1_audit_module",
        lambda: SimpleNamespace(_resolve_db_path=lambda _db: (db, "explicit")),
    )

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["audit"], timeout=1)

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    monkeypatch.setattr(
        mod,
        "_load_gate_queryability_module",
        lambda: SimpleNamespace(
            _fast_queryability_summary=lambda _db: {
                "ok": True,
                "summary": {"frames_total": 9, "frames_queryable": 3, "frames_blocked": 6},
            }
        ),
    )
    payload = mod._run_stage1_audit(  # noqa: SLF001
        db=db,
        derived_db=None,
        gap_seconds=120,
        sample_limit=20,
        frame_limit=100,
        timeout_s=1.0,
    )
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    assert payload.get("warning") == "stage1_audit_timeout"
    assert int(summary.get("frames_total", 0) or 0) == 9
    assert int(summary.get("frames_queryable", 0) or 0) == 3


def test_run_stage1_audit_invalid_output_includes_error(monkeypatch: object, tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    db.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "_load_stage1_audit_module",
        lambda: SimpleNamespace(_resolve_db_path=lambda _db: (db, "explicit")),
    )
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["audit"], returncode=2, stdout="not-json", stderr="boom"
        ),
    )
    payload = mod._run_stage1_audit(  # noqa: SLF001
        db=db,
        derived_db=None,
        gap_seconds=120,
        sample_limit=20,
        frame_limit=100,
        timeout_s=1.0,
    )
    assert payload["ok"] is False
    assert "stage1_audit_invalid_output:rc=2" in str(payload["error"] or "")
