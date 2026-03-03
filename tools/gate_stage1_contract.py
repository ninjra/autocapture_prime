#!/usr/bin/env python3
"""Fail-closed Stage1 minimum contract gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
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


def _parse_iso_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def _derive_freshness_lag_hours(audit: dict[str, Any], summary: dict[str, Any]) -> float | None:
    raw = summary.get("freshness_lag_hours")
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    latest = _parse_iso_utc(summary.get("latest_queryable_ts_utc"))
    if latest is None:
        windows = audit.get("queryable_windows", []) if isinstance(audit.get("queryable_windows", []), list) else []
        for row in windows:
            if not isinstance(row, dict):
                continue
            candidate = _parse_iso_utc(row.get("end_utc"))
            if candidate is None:
                continue
            if latest is None or candidate > latest:
                latest = candidate
    if latest is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() / 3600.0)


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
    max_freshness_lag_hours: float,
) -> dict[str, Any]:
    summary = audit.get("summary", {}) if isinstance(audit.get("summary"), dict) else {}
    plugin_completion = audit.get("plugin_completion", {}) if isinstance(audit.get("plugin_completion"), dict) else {}
    issue_counts = audit.get("issue_counts", {}) if isinstance(audit.get("issue_counts"), dict) else {}

    frames_total = _int(summary.get("frames_total", 0))
    frames_queryable = _int(summary.get("frames_queryable", 0))
    frames_blocked = _int(summary.get("frames_blocked", max(0, frames_total - frames_queryable)))
    ratio = float(frames_queryable / frames_total) if frames_total > 0 else 0.0
    freshness_lag_hours = _derive_freshness_lag_hours(audit, summary)

    reasons: list[str] = []
    if bool(require_frames) and frames_total <= 0:
        reasons.append("no_frames_to_validate")
    if frames_total > 0 and ratio < float(min_queryable_ratio):
        reasons.append("queryable_ratio_below_min")
    if float(max_freshness_lag_hours) > 0.0 and frames_queryable > 0:
        if freshness_lag_hours is None:
            reasons.append("freshness_lag_unknown")
        elif float(freshness_lag_hours) > float(max_freshness_lag_hours):
            reasons.append("freshness_lag_exceeded")

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
            "freshness_lag_hours": (float(freshness_lag_hours) if freshness_lag_hours is not None else None),
        },
        "coverage": coverage,
        "issue_failures": issue_failures,
        "thresholds": {
            "max_freshness_lag_hours": float(max_freshness_lag_hours),
        },
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


def _latest_lineage_report(root: Path) -> Path | None:
    lineage_root = root / "artifacts" / "lineage"
    if not lineage_root.exists():
        return None
    candidates = sorted(
        lineage_root.glob("*/stage1_stage2_lineage_queryability.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_recent_lineage_audit(root: Path, *, max_age_minutes: float) -> tuple[dict[str, Any] | None, str]:
    latest = _latest_lineage_report(root)
    if latest is None:
        return None, ""
    try:
        age_s = max(0.0, time.time() - float(latest.stat().st_mtime))
    except Exception:
        age_s = float("inf")
    max_age_s = max(0.0, float(max_age_minutes) * 60.0)
    if max_age_s > 0.0 and age_s > max_age_s:
        return None, ""
    try:
        payload = _load_json(latest)
    except Exception:
        return None, ""
    # Require the fields needed for stage1 contract evaluation.
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else None
    completion = payload.get("plugin_completion") if isinstance(payload.get("plugin_completion"), dict) else None
    issues = payload.get("issue_counts") if isinstance(payload.get("issue_counts"), dict) else None
    if not isinstance(summary, dict) or not isinstance(completion, dict) or not isinstance(issues, dict):
        return None, ""
    return payload, str(latest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Stage1 minimum contract gate.")
    parser.add_argument("--audit-report", default="", help="Optional precomputed stage1 audit JSON.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Metadata DB path when audit-report is not supplied.")
    parser.add_argument("--derived-db", default="", help="Optional stage1 derived DB override.")
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--audit-timeout-s", type=float, default=120.0)
    parser.add_argument("--min-queryable-ratio", type=float, default=1.0)
    parser.add_argument("--max-freshness-lag-hours", type=float, default=24.0)
    parser.add_argument(
        "--lineage-report-max-age-minutes",
        type=float,
        default=720.0,
        help="When --audit-report is not supplied, allow using latest lineage report if newer than this age.",
    )
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
        repo_root_raw = str(os.environ.get("AUTOCAPTURE_REPO_ROOT") or "").strip()
        repo_root = Path(repo_root_raw).expanduser().resolve() if repo_root_raw else Path(__file__).resolve().parents[1]
        lineage_payload, lineage_path = _load_recent_lineage_audit(
            repo_root,
            max_age_minutes=float(args.lineage_report_max_age_minutes),
        )
        if isinstance(lineage_payload, dict):
            audit = lineage_payload
            audit_source = f"lineage_report:{lineage_path}"
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
        max_freshness_lag_hours=_float(args.max_freshness_lag_hours),
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
