from __future__ import annotations

import subprocess
from pathlib import Path

from tools import frame_plugin_completeness_matrix as mod


def test_build_matrix_counts_missing_plugins() -> None:
    audit = {
        "frame_lineage": [
            {
                "frame_id": "f1",
                "ts_utc": "2026-02-24T00:00:00Z",
                "queryable": True,
                "issues": [],
                "plugins": {
                    "stage1_complete": {"required": True, "ok": True},
                    "retention_eligible": {"required": True, "ok": True},
                    "obs_uia_focus": {"required": True, "ok": True},
                },
            },
            {
                "frame_id": "f2",
                "ts_utc": "2026-02-24T00:00:01Z",
                "queryable": False,
                "issues": ["retention_eligible_missing_or_invalid"],
                "plugins": {
                    "stage1_complete": {"required": True, "ok": True},
                    "retention_eligible": {"required": True, "ok": False},
                    "obs_uia_focus": {"required": True, "ok": False},
                },
            },
        ]
    }
    out = mod.build_matrix(audit)
    assert int(out.get("frames_total", 0) or 0) == 2
    assert int(out.get("frames_complete", 0) or 0) == 1
    assert int(out.get("frames_incomplete", 0) or 0) == 1
    missing_counts = out.get("missing_plugin_counts", {})
    assert isinstance(missing_counts, dict)
    assert int(missing_counts.get("retention_eligible", 0) or 0) == 1
    assert int(missing_counts.get("obs_uia_focus", 0) or 0) == 1


def test_run_stage1_audit_subprocess_timeout(monkeypatch: object, tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    db.write_text("", encoding="utf-8")

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["audit"], timeout=1)

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    payload, err = mod._run_stage1_audit_subprocess(  # noqa: SLF001
        db=db,
        derived_db=None,
        gap_seconds=120,
        sample_limit=20,
        frame_limit=100,
        timeout_s=1.0,
    )
    assert str(err) == "stage1_audit_timeout"
    assert payload["ok"] is False
