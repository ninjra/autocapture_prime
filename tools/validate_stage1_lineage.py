#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import is_stage1_complete_record
from autocapture.storage.stage1 import stage1_complete_record_id
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids
from autocapture_nx.kernel.sqlite_reads import open_sqlite_reader
from autocapture_nx.storage.stage1_derived_store import default_stage1_derived_db_path


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


def _fetch_overlay_row(
    *,
    primary_conn: sqlite3.Connection,
    primary_table: str,
    primary_id_col: str,
    primary_payload_col: str,
    record_id: str,
    secondary_conn: sqlite3.Connection | None,
    secondary_table: str | None,
    secondary_id_col: str | None,
    secondary_payload_col: str | None,
) -> tuple[str, dict[str, Any] | None]:
    if secondary_conn is not None and secondary_table and secondary_id_col and secondary_payload_col:
        s_type, s_payload = _fetch_row(
            secondary_conn,
            table=secondary_table,
            id_col=secondary_id_col,
            payload_col=secondary_payload_col,
            record_id=record_id,
        )
        if s_type or isinstance(s_payload, dict):
            return s_type, s_payload
    return _fetch_row(
        primary_conn,
        table=primary_table,
        id_col=primary_id_col,
        payload_col=primary_payload_col,
        record_id=record_id,
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _valid_bboxes(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            return False
        try:
            left = float(row[0])
            top = float(row[1])
            right = float(row[2])
            bottom = float(row[3])
        except Exception:
            return False
        if right < left or bottom < top:
            return False
    return True


def _validate_obs_payload(
    payload: dict[str, Any] | None,
    *,
    expected_kind: str,
    expected_frame_id: str,
    expected_uia_record_id: str,
    expected_uia_hash: str,
) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{expected_kind}.payload_missing"]
    issues: list[str] = []
    if str(payload.get("record_type") or "") != expected_kind:
        issues.append(f"{expected_kind}.record_type_invalid")
    if not str(payload.get("source_record_id") or "").strip():
        issues.append(f"{expected_kind}.source_record_id_missing")
    if str(payload.get("uia_record_id") or "") != expected_uia_record_id:
        issues.append(f"{expected_kind}.uia_record_id_mismatch")
    if expected_uia_hash and str(payload.get("uia_content_hash") or "") != expected_uia_hash:
        issues.append(f"{expected_kind}.uia_content_hash_mismatch")
    if not str(payload.get("hwnd") or "").strip():
        issues.append(f"{expected_kind}.hwnd_missing")
    if "window_title" not in payload or not isinstance(payload.get("window_title"), str):
        issues.append(f"{expected_kind}.window_title_missing")
    if "window_pid" not in payload or _safe_int(payload.get("window_pid")) < 0:
        issues.append(f"{expected_kind}.window_pid_invalid")
    if not _valid_bboxes(payload.get("bboxes")):
        issues.append(f"{expected_kind}.bbox_invalid")
    return issues


def _validate_stage1_payload(
    payload: dict[str, Any] | None,
    *,
    frame_id: str,
    uia_record_id: str,
    uia_content_hash: str,
) -> list[str]:
    if not isinstance(payload, dict):
        return ["stage1.payload_missing"]
    issues: list[str] = []
    if str(payload.get("record_type") or "") != "derived.ingest.stage1.complete":
        issues.append("stage1.record_type_invalid")
    if not bool(payload.get("complete", False)):
        issues.append("stage1.complete_false")
    if str(payload.get("source_record_id") or "") != str(frame_id):
        issues.append("stage1.source_record_id_mismatch")
    if str(payload.get("source_record_type") or "").strip() != "evidence.capture.frame":
        issues.append("stage1.source_record_type_invalid")
    if uia_record_id and str(payload.get("uia_record_id") or "") != uia_record_id:
        issues.append("stage1.uia_record_id_mismatch")
    if uia_content_hash and str(payload.get("uia_content_hash") or "") != uia_content_hash:
        issues.append("stage1.uia_content_hash_mismatch")
    return issues


def _validate_retention_payload(
    payload: dict[str, Any] | None,
    *,
    frame_id: str,
) -> list[str]:
    if not isinstance(payload, dict):
        return ["retention.payload_missing"]
    issues: list[str] = []
    if str(payload.get("record_type") or "") != "retention.eligible":
        issues.append("retention.record_type_invalid")
    if str(payload.get("source_record_id") or "") != str(frame_id):
        issues.append("retention.source_record_id_mismatch")
    if str(payload.get("source_record_type") or "") != "evidence.capture.frame":
        issues.append("retention.source_record_type_invalid")
    if not bool(payload.get("stage1_contract_validated", False)):
        issues.append("retention.stage1_contract_not_validated")
    if bool(payload.get("quarantine_pending", False)):
        issues.append("retention.quarantine_pending")
    return issues


def _stage1_prereq_issues(frame_id: str, frame: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not isinstance(frame, dict):
        return ["stage1_prereq_invalid_frame_payload"]
    if is_stage1_complete_record(frame_id, frame):
        return issues
    if str(frame.get("record_type") or "") != "evidence.capture.frame":
        issues.append("stage1_prereq_not_frame")
    if not str(frame.get("blob_path") or "").strip():
        issues.append("stage1_prereq_blob_path_missing")
    if not str(frame.get("content_hash") or "").strip():
        issues.append("stage1_prereq_content_hash_missing")
    uia_ref = frame.get("uia_ref") if isinstance(frame.get("uia_ref"), dict) else {}
    if not str(uia_ref.get("record_id") or "").strip():
        issues.append("stage1_prereq_uia_record_id_missing")
    if not str(uia_ref.get("content_hash") or "").strip():
        issues.append("stage1_prereq_uia_content_hash_missing")
    input_ref = frame.get("input_ref") if isinstance(frame.get("input_ref"), dict) else {}
    input_batch_ref = frame.get("input_batch_ref") if isinstance(frame.get("input_batch_ref"), dict) else {}
    has_hid_link = bool(str(input_ref.get("record_id") or "").strip()) or bool(str(input_batch_ref.get("record_id") or "").strip())
    if not has_hid_link:
        issues.append("stage1_prereq_input_ref_missing")
    return issues


def validate_stage1_lineage(
    db_path: Path,
    *,
    derived_db_path: Path | None = None,
    limit: int | None = None,
    sample_count: int = 3,
    strict: bool = False,
    strict_all_frames: bool = False,
    snapshot_read: bool = True,
) -> dict[str, Any]:
    conn, read_info = open_sqlite_reader(
        db_path,
        prefer_snapshot=bool(snapshot_read),
        force_snapshot=False,
    )
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
        "invalid_obs_payload": 0,
        "invalid_stage1_payload": 0,
        "invalid_retention_payload": 0,
        "all_frames_complete": 0,
        "all_frames_incomplete": 0,
        "all_frames_missing_uia_ref": 0,
        "all_frames_missing_stage1": 0,
        "all_frames_missing_retention": 0,
        "all_frames_retention_not_validated": 0,
        "stage1_prereq_missing_counts": {},
        "record_counts": {},
    }
    samples: list[dict[str, Any]] = []
    derived_conn: sqlite3.Connection | None = None
    derived_table: str | None = None
    derived_id_col: str | None = None
    derived_payload_col: str | None = None
    try:
        table, id_col, payload_col = _resolve_table(conn)
        if isinstance(derived_db_path, Path) and derived_db_path.exists():
            derived_conn = sqlite3.connect(str(derived_db_path), timeout=5.0)
            derived_conn.row_factory = sqlite3.Row
            try:
                derived_table, derived_id_col, derived_payload_col = _resolve_table(derived_conn)
            except Exception:
                try:
                    derived_conn.close()
                except Exception:
                    pass
                derived_conn = None
                derived_table = None
                derived_id_col = None
                derived_payload_col = None
        counts: dict[str, int] = {}
        for record_type in ("evidence.capture.frame", "evidence.uia.snapshot"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE record_type = ?", (record_type,)).fetchone()
            counts[record_type] = int(row[0]) if row else 0
        for record_type in ("obs.uia.focus", "obs.uia.context", "obs.uia.operable", "derived.ingest.stage1.complete", "retention.eligible"):
            read_conn = derived_conn if derived_conn is not None else conn
            read_table = derived_table if derived_conn is not None and derived_table else table
            row = read_conn.execute(f"SELECT COUNT(*) FROM {read_table} WHERE record_type = ?", (record_type,)).fetchone()
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
                summary["all_frames_incomplete"] += 1
                continue
            uia_ref = frame.get("uia_ref") if isinstance(frame.get("uia_ref"), dict) else {}
            uia_record_id = str(uia_ref.get("record_id") or "").strip()
            uia_content_hash = str(uia_ref.get("content_hash") or "").strip()

            all_frame_issues: list[str] = []
            stage1_id = stage1_complete_record_id(frame_id)
            stage1_type, stage1_payload = _fetch_overlay_row(
                primary_conn=conn,
                primary_table=table,
                primary_id_col=id_col,
                primary_payload_col=payload_col,
                record_id=stage1_id,
                secondary_conn=derived_conn,
                secondary_table=derived_table,
                secondary_id_col=derived_id_col,
                secondary_payload_col=derived_payload_col,
            )
            if stage1_type != "derived.ingest.stage1.complete":
                summary["all_frames_missing_stage1"] += 1
                all_frame_issues.append("missing_stage1")
                prereq_issues = _stage1_prereq_issues(frame_id, frame)
                for issue in prereq_issues:
                    counts = summary.get("stage1_prereq_missing_counts")
                    if not isinstance(counts, dict):
                        counts = {}
                        summary["stage1_prereq_missing_counts"] = counts
                    counts[str(issue)] = int(counts.get(str(issue), 0) or 0) + 1
                all_frame_issues.extend(prereq_issues)
            else:
                stage1_payload_issues = _validate_stage1_payload(
                    stage1_payload,
                    frame_id=frame_id,
                    uia_record_id=uia_record_id,
                    uia_content_hash=uia_content_hash,
                )
                if stage1_payload_issues:
                    summary["invalid_stage1_payload"] += 1
                    all_frame_issues.extend(stage1_payload_issues)

            retention_id = retention_eligibility_record_id(frame_id)
            retention_type, retention_payload = _fetch_overlay_row(
                primary_conn=conn,
                primary_table=table,
                primary_id_col=id_col,
                primary_payload_col=payload_col,
                record_id=retention_id,
                secondary_conn=derived_conn,
                secondary_table=derived_table,
                secondary_id_col=derived_id_col,
                secondary_payload_col=derived_payload_col,
            )
            if retention_type != "retention.eligible":
                summary["all_frames_missing_retention"] += 1
                all_frame_issues.append("missing_retention")
            else:
                retention_payload_issues = _validate_retention_payload(retention_payload, frame_id=frame_id)
                if retention_payload_issues:
                    summary["invalid_retention_payload"] += 1
                    all_frame_issues.extend(retention_payload_issues)
                if (
                    not bool(retention_payload.get("stage1_contract_validated", False))
                    or bool(retention_payload.get("quarantine_pending", False))
                ):
                    summary["all_frames_retention_not_validated"] += 1

            if all_frame_issues:
                summary["all_frames_incomplete"] += 1
            else:
                summary["all_frames_complete"] += 1

            if not uia_record_id:
                summary["all_frames_missing_uia_ref"] += 1
                if strict_all_frames and len(samples) < max(0, int(sample_count)):
                    samples.append({"frame_id": frame_id, "uia_record_id": "", "issues": list(all_frame_issues + ["missing_uia_ref"])})
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
                obs_type, obs_payload = _fetch_overlay_row(
                    primary_conn=conn,
                    primary_table=table,
                    primary_id_col=id_col,
                    primary_payload_col=payload_col,
                    record_id=obs_id,
                    secondary_conn=derived_conn,
                    secondary_table=derived_table,
                    secondary_id_col=derived_id_col,
                    secondary_payload_col=derived_payload_col,
                )
                if obs_type != kind:
                    summary["missing_obs_docs"] += 1
                    issues.append(f"missing_{kind}")
                    continue
                obs_payload_issues = _validate_obs_payload(
                    obs_payload,
                    expected_kind=kind,
                    expected_frame_id=frame_id,
                    expected_uia_record_id=uia_record_id,
                    expected_uia_hash=uia_content_hash,
                )
                if obs_payload_issues:
                    summary["invalid_obs_payload"] += 1
                    issues.extend(obs_payload_issues)

            if stage1_type != "derived.ingest.stage1.complete" or not isinstance(stage1_payload, dict):
                summary["missing_stage1"] += 1
                issues.append("missing_stage1")
            else:
                stage1_payload_issues = _validate_stage1_payload(
                    stage1_payload,
                    frame_id=frame_id,
                    uia_record_id=uia_record_id,
                    uia_content_hash=uia_content_hash,
                )
                if stage1_payload_issues:
                    summary["invalid_stage1_payload"] += 1
                    issues.extend(stage1_payload_issues)

            if retention_type != "retention.eligible" or not isinstance(retention_payload, dict):
                summary["missing_retention"] += 1
                issues.append("missing_retention")
            else:
                retention_payload_issues = _validate_retention_payload(retention_payload, frame_id=frame_id)
                if retention_payload_issues:
                    summary["invalid_retention_payload"] += 1
                    issues.extend(retention_payload_issues)
                if (
                    not bool(retention_payload.get("stage1_contract_validated", False))
                    or bool(retention_payload.get("quarantine_pending", False))
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
        if derived_conn is not None:
            derived_conn.close()
        conn.close()

    fail_reasons: list[str] = []
    if int(summary.get("frames_with_uia_ref", 0) or 0) <= 0:
        fail_reasons.append("no_frames_with_uia_ref")
    if int(summary.get("lineage_complete", 0) or 0) <= 0:
        fail_reasons.append("lineage_complete_zero")
    if strict and int(summary.get("lineage_incomplete", 0) or 0) > 0:
        fail_reasons.append("strict_lineage_incomplete_nonzero")
    if strict_all_frames and int(summary.get("all_frames_incomplete", 0) or 0) > 0:
        fail_reasons.append("strict_all_frames_incomplete_nonzero")
    ok = len(fail_reasons) == 0
    return {
        "ok": ok,
        "strict": bool(strict),
        "strict_all_frames": bool(strict_all_frames),
        "db_read": read_info,
        "summary": summary,
        "samples": samples,
        "fail_reasons": fail_reasons,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Stage1/UIA lineage readiness from metadata DB.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata DB.")
    parser.add_argument("--derived-db", default="", help="Optional stage1 derived DB path (default: <db dir>/derived/stage1_derived.db if present).")
    parser.add_argument("--limit", type=int, default=0, help="Optional max frame rows to scan (0 = all).")
    parser.add_argument("--samples", type=int, default=3, help="How many lineage sample rows to emit.")
    parser.add_argument("--strict", action="store_true", help="Fail when any uia_ref lineage is incomplete.")
    parser.add_argument("--strict-all-frames", action="store_true", help="Fail when any capture frame is missing stage1/retention-ready lineage.")
    parser.add_argument("--snapshot-read", dest="snapshot_read", action="store_true", help="Allow direct read with snapshot fallback.")
    parser.add_argument("--no-snapshot-read", dest="snapshot_read", action="store_false", help="Disable snapshot fallback and read DB directly.")
    parser.set_defaults(snapshot_read=True)
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
    derived_db_path: Path | None = None
    derived_arg = str(args.derived_db or "").strip()
    if derived_arg:
        derived_db_path = Path(derived_arg).expanduser()
    else:
        candidate = default_stage1_derived_db_path(db_path.parent)
        if candidate.exists():
            derived_db_path = candidate
    try:
        payload = validate_stage1_lineage(
            db_path,
            derived_db_path=derived_db_path,
            limit=int(args.limit) if int(args.limit) > 0 else None,
            sample_count=int(args.samples),
            strict=bool(args.strict),
            strict_all_frames=bool(args.strict_all_frames),
            snapshot_read=bool(args.snapshot_read),
        )
    except Exception as exc:
        out = {"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(db_path)}
        print(json.dumps(out, sort_keys=True))
        return 1
    payload["db"] = str(db_path)
    payload["derived_db"] = str(derived_db_path) if isinstance(derived_db_path, Path) else ""
    if str(args.output or "").strip():
        out_path = Path(str(args.output)).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 3


if __name__ == "__main__":
    raise SystemExit(main())
