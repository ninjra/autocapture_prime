#!/usr/bin/env python3
"""Fail-closed Stage1 minimum contract gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REQUIRED_STAGE1_KEYS = (
    "stage1_complete",
    "retention_eligible",
    "uia_snapshot",
    "obs_uia_focus",
    "obs_uia_context",
    "obs_uia_operable",
)

BLOCKING_ISSUE_KEYS = (
    "stage1_complete_missing_or_invalid",
    "retention_eligible_missing_or_invalid",
    "uia_snapshot_missing",
    "obs_uia_focus_missing_or_invalid",
    "obs_uia_context_missing_or_invalid",
    "obs_uia_operable_missing_or_invalid",
)


def _int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid_json_object:{path}")
    return payload


def evaluate_stage1_contract(
    *,
    audit: dict[str, Any],
    min_queryable_ratio: float,
    require_frames: bool,
) -> dict[str, Any]:
    summary = audit.get("summary", {}) if isinstance(audit.get("summary"), dict) else {}
    plugin_completion = audit.get("plugin_completion", {}) if isinstance(audit.get("plugin_completion"), dict) else {}
    issue_counts = audit.get("issue_counts", {}) if isinstance(audit.get("issue_counts"), dict) else {}

    frames_total = _int(summary.get("frames_total", 0))
    frames_queryable = _int(summary.get("frames_queryable", 0))
    frames_blocked = _int(summary.get("frames_blocked", max(0, frames_total - frames_queryable)))
    ratio = float(frames_queryable / frames_total) if frames_total > 0 else 0.0

    reasons: list[str] = []
    if bool(require_frames) and frames_total <= 0:
        reasons.append("no_frames_to_validate")
    if frames_total > 0 and ratio < float(min_queryable_ratio):
        reasons.append("queryable_ratio_below_min")

    coverage: dict[str, dict[str, int | bool]] = {}
    for key in REQUIRED_STAGE1_KEYS:
        row = plugin_completion.get(key, {}) if isinstance(plugin_completion.get(key), dict) else {}
        ok_count = _int(row.get("ok", 0))
        required_count = _int(row.get("required", 0))
        has_gap = required_count > ok_count
        coverage[key] = {
            "ok": ok_count,
            "required": required_count,
            "has_gap": bool(has_gap),
        }
        if has_gap:
            reasons.append(f"{key}_coverage_gap")

    issue_failures: dict[str, int] = {}
    for key in BLOCKING_ISSUE_KEYS:
        count = _int(issue_counts.get(key, 0))
        if count > 0:
            issue_failures[key] = count
    if issue_failures:
        reasons.append("blocking_issue_counts_nonzero")

    deduped_reasons = sorted(set(str(item) for item in reasons if str(item)))
    return {
        "ok": len(deduped_reasons) == 0,
        "reasons": deduped_reasons,
        "min_queryable_ratio": float(min_queryable_ratio),
        "queryable_ratio": float(round(ratio, 6)),
        "counts": {
            "frames_total": int(frames_total),
            "frames_queryable": int(frames_queryable),
            "frames_blocked": int(max(0, frames_blocked)),
        },
        "coverage": coverage,
        "issue_failures": issue_failures,
    }


def _run_stage1_audit(
    *,
    db: Path,
    derived_db: Path | None,
    gap_seconds: int,
    sample_limit: int,
    frame_limit: int,
    timeout_s: float,
) -> tuple[dict[str, Any], str]:
    cmd = [
        str(sys.executable),
        "tools/soak/stage1_completeness_audit.py",
        "--db",
        str(db),
        "--gap-seconds",
        str(int(gap_seconds)),
        "--samples",
        str(int(sample_limit)),
        "--frame-limit",
        str(int(frame_limit)),
    ]
    if isinstance(derived_db, Path):
        cmd.extend(["--derived-db", str(derived_db)])
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "stage1_audit_timeout"}, "stage1_audit_timeout"
    stdout = str(proc.stdout or "").strip()
    if not stdout:
        return {"ok": False, "error": f"stage1_audit_empty_output:rc={int(proc.returncode)}"}, "stage1_audit_empty_output"
    try:
        payload = json.loads(stdout)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not payload:
        return {"ok": False, "error": f"stage1_audit_invalid_output:rc={int(proc.returncode)}"}, "stage1_audit_invalid_output"
    return payload, ""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Stage1 minimum contract gate.")
    parser.add_argument("--audit-report", default="", help="Optional precomputed stage1 audit JSON.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Metadata DB path when audit-report is not supplied.")
    parser.add_argument("--derived-db", default="", help="Optional stage1 derived DB override.")
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--audit-timeout-s", type=float, default=10.0)
    parser.add_argument("--min-queryable-ratio", type=float, default=1.0)
    parser.add_argument("--require-frames", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--output", default="artifacts/stage1_contract/gate_stage1_contract.json")
    args = parser.parse_args(argv)

    audit_source = ""
    audit: dict[str, Any]
    if str(args.audit_report or "").strip():
        report_path = Path(str(args.audit_report).strip()).expanduser()
        audit = _load_json(report_path)
        audit_source = f"audit_report:{report_path}"
    else:
        db = Path(str(args.db)).expanduser()
        derived_db = Path(str(args.derived_db)).expanduser() if str(args.derived_db or "").strip() else None
        audit, audit_err = _run_stage1_audit(
            db=db,
            derived_db=derived_db,
            gap_seconds=int(args.gap_seconds),
            sample_limit=int(args.sample_limit),
            frame_limit=int(args.frame_limit),
            timeout_s=float(args.audit_timeout_s),
        )
        audit_source = f"audit_subprocess:{db}"
        if audit_err:
            payload = {
                "schema_version": 1,
                "ok": False,
                "error": str(audit_err),
                "audit_source": audit_source,
            }
            out_path = Path(str(args.output)).expanduser()
            _write_json(out_path, payload)
            payload["output"] = str(out_path)
            print(json.dumps(payload, sort_keys=True))
            return 1

    evaluated = evaluate_stage1_contract(
        audit=audit,
        min_queryable_ratio=_float(args.min_queryable_ratio),
        require_frames=bool(args.require_frames),
    )
    payload = {
        "schema_version": 1,
        "ok": bool(evaluated.get("ok", False)),
        "audit_source": audit_source,
        "result": evaluated,
    }
    out_path = Path(str(args.output)).expanduser()
    _write_json(out_path, payload)
    payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

