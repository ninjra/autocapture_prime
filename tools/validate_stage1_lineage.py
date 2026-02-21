#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import stage1_complete_record_id
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return dict(value) if isinstance(value, dict) else None


def _resolve_table(conn: sqlite3.Connection) -> tuple[str, str, str]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "metadata" in tables:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
        if "record_type" in cols and "payload" in cols and "id" in cols:
            return "metadata", "id", "payload"
    if "records" in tables:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(records)").fetchall()}
        if "record_type" in cols and "json" in cols and "id" in cols:
            return "records", "id", "json"
    raise RuntimeError("no_supported_metadata_table")


def _fetch_row(conn: sqlite3.Connection, *, table: str, id_col: str, payload_col: str, record_id: str) -> tuple[str, dict[str, Any] | None]:
    row = conn.execute(f"SELECT record_type, {payload_col} FROM {table} WHERE {id_col} = ?", (str(record_id),)).fetchone()
    if not row:
        return "", None
    return str(row[0] or ""), _parse_payload(row[1])


def validate_stage1_lineage(
    db_path: Path,
    *,
    limit: int | None = None,
    sample_count: int = 3,
    strict: bool = False,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    summary: dict[str, Any] = {
        "frames_scanned": 0,
        "frames_with_uia_ref": 0,
        "lineage_complete": 0,
        "lineage_incomplete": 0,
        "missing_snapshot": 0,
        "missing_obs_docs": 0,
        "missing_stage1": 0,
        "missing_retention": 0,
        "retention_not_validated": 0,
        "record_counts": {},
    }
    samples: list[dict[str, Any]] = []
    try:
        table, id_col, payload_col = _resolve_table(conn)
        counts: dict[str, int] = {}
        for record_type in (
            "evidence.capture.frame",
            "evidence.uia.snapshot",
            "obs.uia.focus",
            "obs.uia.context",
            "obs.uia.operable",
            "derived.ingest.stage1.complete",
            "retention.eligible",
        ):
            row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE record_type = ?", (record_type,)).fetchone()
            counts[record_type] = int(row[0]) if row else 0
        summary["record_counts"] = counts

        sql = f"SELECT {id_col}, {payload_col} FROM {table} WHERE record_type = ? ORDER BY {id_col}"
        params: list[Any] = ["evidence.capture.frame"]
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        for row in conn.execute(sql, tuple(params)):
            summary["frames_scanned"] += 1
            frame_id = str(row[id_col] or "")
            frame = _parse_payload(row[payload_col])
            if not isinstance(frame, dict):
                summary["lineage_incomplete"] += 1
                continue
            uia_ref = frame.get("uia_ref") if isinstance(frame.get("uia_ref"), dict) else {}
            uia_record_id = str(uia_ref.get("record_id") or "").strip()
            if not uia_record_id:
                continue
            summary["frames_with_uia_ref"] += 1

            issues: list[str] = []
            snapshot_type, _snapshot = _fetch_row(
                conn,
                table=table,
                id_col=id_col,
                payload_col=payload_col,
                record_id=uia_record_id,
            )
            if snapshot_type != "evidence.uia.snapshot":
                summary["missing_snapshot"] += 1
                issues.append("missing_snapshot")

            expected_obs = _frame_uia_expected_ids(uia_record_id)
            for kind, obs_id in expected_obs.items():
                obs_type, _obs_payload = _fetch_row(
                    conn,
                    table=table,
                    id_col=id_col,
                    payload_col=payload_col,
                    record_id=obs_id,
                )
                if obs_type != kind:
                    summary["missing_obs_docs"] += 1
                    issues.append(f"missing_{kind}")

            stage1_id = stage1_complete_record_id(frame_id)
            stage1_type, stage1_payload = _fetch_row(
                conn,
                table=table,
                id_col=id_col,
                payload_col=payload_col,
                record_id=stage1_id,
            )
            if stage1_type != "derived.ingest.stage1.complete" or not isinstance(stage1_payload, dict):
                summary["missing_stage1"] += 1
                issues.append("missing_stage1")

            retention_id = retention_eligibility_record_id(frame_id)
            retention_type, retention_payload = _fetch_row(
                conn,
                table=table,
                id_col=id_col,
                payload_col=payload_col,
                record_id=retention_id,
            )
            if retention_type != "retention.eligible" or not isinstance(retention_payload, dict):
                summary["missing_retention"] += 1
                issues.append("missing_retention")
            else:
                if not bool(retention_payload.get("stage1_contract_validated", False)) or bool(
                    retention_payload.get("quarantine_pending", False)
                ):
                    summary["retention_not_validated"] += 1
                    issues.append("retention_not_validated")

            if issues:
                summary["lineage_incomplete"] += 1
                if len(samples) < max(0, int(sample_count)):
                    samples.append(
                        {
                            "frame_id": frame_id,
                            "uia_record_id": uia_record_id,
                            "issues": issues,
                        }
                    )
                continue

            summary["lineage_complete"] += 1
            if len(samples) < max(0, int(sample_count)):
                samples.append(
                    {
                        "frame_id": frame_id,
                        "uia_record_id": uia_record_id,
                        "obs_ids": expected_obs,
                        "stage1_id": stage1_id,
                        "retention_id": retention_id,
                        "issues": [],
                    }
                )
    finally:
        conn.close()

    fail_reasons: list[str] = []
    if int(summary.get("frames_with_uia_ref", 0) or 0) <= 0:
        fail_reasons.append("no_frames_with_uia_ref")
    if int(summary.get("lineage_complete", 0) or 0) <= 0:
        fail_reasons.append("lineage_complete_zero")
    if strict and int(summary.get("lineage_incomplete", 0) or 0) > 0:
        fail_reasons.append("strict_lineage_incomplete_nonzero")
    ok = len(fail_reasons) == 0
    return {
        "ok": ok,
        "strict": bool(strict),
        "summary": summary,
        "samples": samples,
        "fail_reasons": fail_reasons,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Stage1/UIA lineage readiness from metadata DB.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata DB.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max frame rows to scan (0 = all).")
    parser.add_argument("--samples", type=int, default=3, help="How many lineage sample rows to emit.")
    parser.add_argument("--strict", action="store_true", help="Fail when any uia_ref lineage is incomplete.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    if not db_path.exists():
        out = {"ok": False, "error": "db_not_found", "db": str(db_path)}
        print(json.dumps(out, sort_keys=True))
        return 2
    try:
        payload = validate_stage1_lineage(
            db_path,
            limit=int(args.limit) if int(args.limit) > 0 else None,
            sample_count=int(args.samples),
            strict=bool(args.strict),
        )
    except Exception as exc:
        out = {"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(db_path)}
        print(json.dumps(out, sort_keys=True))
        return 1
    payload["db"] = str(db_path)
    if str(args.output or "").strip():
        out_path = Path(str(args.output)).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 3


if __name__ == "__main__":
    raise SystemExit(main())
