from __future__ import annotations

import subprocess
import json
import sqlite3
from pathlib import Path

from tools import gate_queryability as mod


def test_evaluate_queryability_passes_when_all_processed_are_queryable() -> None:
    audit = {
        "summary": {
            "frames_total": 5,
            "frames_queryable": 5,
        },
        "plugin_completion": {
            "stage1_complete": {"ok": 5, "required": 5},
            "retention_eligible": {"ok": 5, "required": 5},
        },
        "issue_counts": {
            "retention_eligible_missing_or_invalid": 0,
        },
    }
    out = mod.evaluate_queryability(audit=audit, min_ratio=1.0)
    assert out["ok"] is True
    assert out["reasons"] == []
    assert float(out["queryable_ratio"]) == 1.0


def test_evaluate_queryability_fails_when_processed_frames_blocked() -> None:
    audit = {
        "summary": {
            "frames_total": 7,
            "frames_queryable": 3,
        },
        "plugin_completion": {
            "stage1_complete": {"ok": 6, "required": 7},
            "retention_eligible": {"ok": 4, "required": 7},
        },
        "issue_counts": {
            "retention_eligible_missing_or_invalid": 2,
        },
    }
    out = mod.evaluate_queryability(audit=audit, min_ratio=0.95)
    assert out["ok"] is False
    reasons = set(str(x) for x in out["reasons"])
    assert "processed_frames_missing_queryability" in reasons
    assert "queryable_ratio_below_min" in reasons
    assert "retention_gap_for_processed_frames" in reasons
    assert int((out["counts"] or {}).get("blocked_stage1_frames", 0) or 0) == 3


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


def test_fast_queryability_summary_from_metadata_table(tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE metadata (id TEXT PRIMARY KEY, record_type TEXT, ts_utc TEXT, payload TEXT, run_id TEXT)"
        )
        frame_id = "run/evidence.capture.frame/1"
        conn.execute(
            "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
            (frame_id, "evidence.capture.frame", "2026-02-24T00:00:00Z", json.dumps({"record_type": "evidence.capture.frame"}), "run"),
        )
        conn.execute(
            "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
            (
                "run/derived.ingest.stage1.complete/a",
                "derived.ingest.stage1.complete",
                "2026-02-24T00:00:01Z",
                json.dumps(
                    {
                        "record_type": "derived.ingest.stage1.complete",
                        "source_record_id": frame_id,
                        "source_record_type": "evidence.capture.frame",
                        "complete": True,
                    }
                ),
                "run",
            ),
        )
        conn.execute(
            "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
            (
                "run/retention.eligible/a",
                "retention.eligible",
                "2026-02-24T00:00:02Z",
                json.dumps(
                    {
                        "record_type": "retention.eligible",
                        "source_record_id": frame_id,
                        "source_record_type": "evidence.capture.frame",
                        "stage1_contract_validated": True,
                        "quarantine_pending": False,
                    }
                ),
                "run",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    out = mod._fast_queryability_summary(db)  # noqa: SLF001
    summary = out.get("summary", {})
    assert int(summary.get("frames_total", 0) or 0) == 1
    assert int(summary.get("frames_queryable", 0) or 0) == 1
    plugin = out.get("plugin_completion", {})
    assert int((plugin.get("stage1_complete") or {}).get("ok", 0) or 0) == 1
    assert int((plugin.get("retention_eligible") or {}).get("ok", 0) or 0) == 1
