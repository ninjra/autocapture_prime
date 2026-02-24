#!/usr/bin/env python3
"""Fail-closed queryability gate.

Blocks release when Stage1-processed frames are not queryable from normalized
records with required linkage/plugin outputs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from autocapture_nx.storage.stage1_derived_store import default_stage1_derived_db_path


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected_json_object:{path}")
    return payload


def _load_stage1_audit_module() -> Any:
    mod_path = Path("tools/soak/stage1_completeness_audit.py").resolve()
    spec = importlib.util.spec_from_file_location("stage1_completeness_audit_for_gate", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_stage1_completeness_audit_module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def evaluate_queryability(*, audit: dict[str, Any], min_ratio: float) -> dict[str, Any]:
    summary = audit.get("summary", {}) if isinstance(audit.get("summary", {}), dict) else {}
    plugin_completion = audit.get("plugin_completion", {}) if isinstance(audit.get("plugin_completion", {}), dict) else {}
    issue_counts = audit.get("issue_counts", {}) if isinstance(audit.get("issue_counts", {}), dict) else {}

    frames_total = _int(summary.get("frames_total", 0))
    frames_queryable = _int(summary.get("frames_queryable", 0))
    stage1 = plugin_completion.get("stage1_complete", {}) if isinstance(plugin_completion.get("stage1_complete", {}), dict) else {}
    retention = plugin_completion.get("retention_eligible", {}) if isinstance(plugin_completion.get("retention_eligible", {}), dict) else {}
    stage1_ok = _int(stage1.get("ok", 0))
    stage1_required = _int(stage1.get("required", 0))
    retention_ok = _int(retention.get("ok", 0))
    blocked_stage1_frames = max(0, int(stage1_ok - frames_queryable))
    ratio_den = stage1_ok if stage1_ok > 0 else frames_total
    ratio = float(frames_queryable / ratio_den) if ratio_den > 0 else 0.0
    reasons: list[str] = []

    if stage1_ok > 0 and frames_queryable <= 0:
        reasons.append("processed_frames_not_queryable")
    if stage1_ok > 0 and blocked_stage1_frames > 0:
        reasons.append("processed_frames_missing_queryability")
    if ratio_den > 0 and ratio < float(min_ratio):
        reasons.append("queryable_ratio_below_min")
    if stage1_ok > retention_ok:
        reasons.append("retention_gap_for_processed_frames")
    if stage1_required > 0 and stage1_ok <= 0:
        reasons.append("stage1_markers_missing")
    if _int(issue_counts.get("retention_eligible_missing_or_invalid", 0)) > 0 and stage1_ok > 0:
        reasons.append("retention_records_invalid")

    ok = len(reasons) == 0
    return {
        "ok": bool(ok),
        "reasons": reasons,
        "counts": {
            "frames_total": int(frames_total),
            "frames_queryable": int(frames_queryable),
            "stage1_ok": int(stage1_ok),
            "stage1_required": int(stage1_required),
            "retention_ok": int(retention_ok),
            "blocked_stage1_frames": int(blocked_stage1_frames),
        },
        "queryable_ratio": float(round(ratio, 6)),
        "min_queryable_ratio": float(min_ratio),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _run_stage1_audit_subprocess(
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
            check=False,
            timeout=max(1.0, float(timeout_s)),
        )
    except subprocess.TimeoutExpired:
        return (
            {
                "ok": False,
                "error": "stage1_audit_timeout",
                "summary": {},
                "plugin_completion": {},
                "issue_counts": {},
            },
            "stage1_audit_timeout",
        )
    stdout = str(proc.stdout or "").strip()
    if not stdout:
        return (
            {
                "ok": False,
                "error": f"stage1_audit_empty_output:rc={int(proc.returncode)}",
                "summary": {},
                "plugin_completion": {},
                "issue_counts": {},
            },
            "stage1_audit_empty_output",
        )
    try:
        payload = json.loads(stdout)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not payload:
        return (
            {
                "ok": False,
                "error": f"stage1_audit_invalid_output:rc={int(proc.returncode)}",
                "summary": {},
                "plugin_completion": {},
                "issue_counts": {},
            },
            "stage1_audit_invalid_output",
        )
    return payload, ""


def _resolve_sql_table(conn: sqlite3.Connection) -> tuple[str, str, str]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "metadata" in tables:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
        if {"id", "record_type", "payload"}.issubset(cols):
            return "metadata", "id", "payload"
    if "records" in tables:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(records)").fetchall()}
        if {"id", "record_type", "json"}.issubset(cols):
            return "records", "id", "json"
    raise RuntimeError("no_supported_metadata_table")


def _fast_queryability_summary(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        table, _id_col, payload_col = _resolve_sql_table(conn)
        frames_total = _int(
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE record_type = 'evidence.capture.frame'").fetchone()[0]
        )
        stage1_ok = _int(
            conn.execute(
                (
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE record_type = 'derived.ingest.stage1.complete' "
                    f"AND json_extract({payload_col}, '$.source_record_type') = 'evidence.capture.frame' "
                    f"AND json_extract({payload_col}, '$.complete') = 1 "
                    f"AND length(coalesce(json_extract({payload_col}, '$.source_record_id'), '')) > 0"
                )
            ).fetchone()[0]
        )
        retention_ok = _int(
            conn.execute(
                (
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE record_type = 'retention.eligible' "
                    f"AND json_extract({payload_col}, '$.source_record_type') = 'evidence.capture.frame' "
                    f"AND json_extract({payload_col}, '$.stage1_contract_validated') = 1 "
                    f"AND coalesce(json_extract({payload_col}, '$.quarantine_pending'), 0) = 0"
                )
            ).fetchone()[0]
        )
        queryable = int(min(stage1_ok, retention_ok))
        blocked = int(max(0, stage1_ok - queryable))
        return {
            "ok": True,
            "mode": "fast_sql",
            "summary": {
                "frames_total": int(frames_total),
                "frames_queryable": int(queryable),
                "frames_blocked": int(max(0, frames_total - queryable)),
                "contiguous_queryable_windows": 0,
            },
            "plugin_completion": {
                "stage1_complete": {"ok": int(stage1_ok), "required": int(frames_total)},
                "retention_eligible": {"ok": int(retention_ok), "required": int(frames_total)},
            },
            "issue_counts": {
                "retention_eligible_missing_or_invalid": int(blocked),
            },
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed queryability gate over Stage1 completeness audit.")
    parser.add_argument("--audit-report", default="", help="Optional precomputed stage1 completeness audit report.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Metadata DB path when audit-report is not supplied.")
    parser.add_argument("--derived-db", default="", help="Optional derived DB override.")
    parser.add_argument("--min-queryable-ratio", type=float, default=1.0)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--audit-timeout-s", type=float, default=10.0)
    parser.add_argument("--output", default="artifacts/queryability/gate_queryability.json")
    args = parser.parse_args(argv)

    audit: dict[str, Any]
    audit_source = ""
    audit_report = Path(str(args.audit_report).strip()) if str(args.audit_report).strip() else None
    if isinstance(audit_report, Path):
        audit = _load_json(audit_report)
        audit_source = str(audit_report.resolve())
    else:
        module = _load_stage1_audit_module()
        requested_db = Path(str(args.db)).expanduser()
        resolved_db, _resolved_reason = module._resolve_db_path(requested_db)  # noqa: SLF001
        if not resolved_db.exists():
            print(json.dumps({"ok": False, "error": "db_not_found", "db": str(resolved_db)}, sort_keys=True))
            return 2
        derived_db: Path | None = None
        if str(args.derived_db or "").strip():
            derived_db = Path(str(args.derived_db)).expanduser()
        else:
            candidate = default_stage1_derived_db_path(resolved_db.parent)
            if candidate.exists():
                derived_db = candidate
        audit, audit_err = _run_stage1_audit_subprocess(
            db=resolved_db,
            derived_db=derived_db,
            gap_seconds=int(args.gap_seconds),
            sample_limit=int(args.sample_limit),
            frame_limit=int(args.frame_limit),
            timeout_s=float(args.audit_timeout_s),
        )
        if audit_err:
            try:
                audit = _fast_queryability_summary(resolved_db)
            except Exception:
                payload = {
                    "schema_version": 1,
                    "ok": False,
                    "audit_source": str(resolved_db.resolve()),
                    "evaluation": {
                        "ok": False,
                        "reasons": [str(audit_err)],
                        "counts": {
                            "frames_total": 0,
                            "frames_queryable": 0,
                            "stage1_ok": 0,
                            "stage1_required": 0,
                            "retention_ok": 0,
                            "blocked_stage1_frames": 0,
                        },
                        "queryable_ratio": 0.0,
                        "min_queryable_ratio": float(max(0.0, min(1.0, _float(args.min_queryable_ratio)))),
                    },
                }
                out_path = Path(str(args.output)).expanduser()
                _write_json(out_path, payload)
                print(json.dumps({"ok": False, "output": str(out_path.resolve())}, sort_keys=True))
                return 1
        audit_source = str(resolved_db.resolve())

    outcome = evaluate_queryability(
        audit=audit,
        min_ratio=max(0.0, min(1.0, _float(args.min_queryable_ratio))),
    )
    payload = {
        "schema_version": 1,
        "ok": bool(outcome.get("ok", False)),
        "audit_source": audit_source,
        "evaluation": outcome,
    }
    out_path = Path(str(args.output)).expanduser()
    _write_json(out_path, payload)
    print(json.dumps({"ok": bool(payload.get("ok", False)), "output": str(out_path.resolve())}, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
