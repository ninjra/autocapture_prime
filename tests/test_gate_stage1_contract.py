from __future__ import annotations

import json
from pathlib import Path

from tools import gate_stage1_contract as mod


def test_evaluate_stage1_contract_passes_with_full_coverage() -> None:
    audit = {
        "summary": {
            "frames_total": 2,
            "frames_queryable": 2,
            "frames_blocked": 0,
        },
        "plugin_completion": {
            "stage1_complete": {"ok": 2, "required": 2},
            "retention_eligible": {"ok": 2, "required": 2},
            "uia_snapshot": {"ok": 2, "required": 2},
            "obs_uia_focus": {"ok": 2, "required": 2},
            "obs_uia_context": {"ok": 2, "required": 2},
            "obs_uia_operable": {"ok": 2, "required": 2},
        },
        "issue_counts": {},
    }
    out = mod.evaluate_stage1_contract(audit=audit, min_queryable_ratio=1.0, require_frames=True)
    assert out["ok"] is True
    assert out["reasons"] == []
    assert float(out["queryable_ratio"]) == 1.0


def test_evaluate_stage1_contract_fails_on_gaps_and_issue_counts() -> None:
    audit = {
        "summary": {
            "frames_total": 3,
            "frames_queryable": 1,
            "frames_blocked": 2,
        },
        "plugin_completion": {
            "stage1_complete": {"ok": 3, "required": 3},
            "retention_eligible": {"ok": 2, "required": 3},
            "uia_snapshot": {"ok": 2, "required": 3},
            "obs_uia_focus": {"ok": 2, "required": 3},
            "obs_uia_context": {"ok": 2, "required": 3},
            "obs_uia_operable": {"ok": 2, "required": 3},
        },
        "issue_counts": {
            "retention_eligible_missing_or_invalid": 1,
            "obs_uia_focus_missing_or_invalid": 1,
        },
    }
    out = mod.evaluate_stage1_contract(audit=audit, min_queryable_ratio=1.0, require_frames=True)
    assert out["ok"] is False
    reasons = set(str(item) for item in out["reasons"])
    assert "queryable_ratio_below_min" in reasons
    assert "retention_eligible_coverage_gap" in reasons
    assert "blocking_issue_counts_nonzero" in reasons
    assert int((out.get("issue_failures") or {}).get("retention_eligible_missing_or_invalid", 0) or 0) == 1


def test_main_uses_audit_report_and_writes_output(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.json"
    out_path = tmp_path / "gate.json"
    audit_payload = {
        "summary": {"frames_total": 1, "frames_queryable": 1, "frames_blocked": 0},
        "plugin_completion": {
            "stage1_complete": {"ok": 1, "required": 1},
            "retention_eligible": {"ok": 1, "required": 1},
            "uia_snapshot": {"ok": 1, "required": 1},
            "obs_uia_focus": {"ok": 1, "required": 1},
            "obs_uia_context": {"ok": 1, "required": 1},
            "obs_uia_operable": {"ok": 1, "required": 1},
        },
        "issue_counts": {},
    }
    audit_path.write_text(json.dumps(audit_payload), encoding="utf-8")
    rc = mod.main(["--audit-report", str(audit_path), "--output", str(out_path), "--require-frames"])
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert str(payload["audit_source"]).startswith("audit_report:")

