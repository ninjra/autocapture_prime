#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import stage1_complete_record_id
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids
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
        row_type, row_payload = _fetch_row(
            secondary_conn,
            table=secondary_table,
            id_col=secondary_id_col,
            payload_col=secondary_payload_col,
            record_id=record_id,
        )
        if row_type or isinstance(row_payload, dict):
            return row_type, row_payload
    return _fetch_row(
        primary_conn,
        table=primary_table,
        id_col=primary_id_col,
        payload_col=primary_payload_col,
        record_id=record_id,
    )


def _parse_ts_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


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


def _obs_payload_ok(payload: dict[str, Any] | None, *, kind: str, uia_record_id: str, uia_hash: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("record_type") or "") != str(kind):
        return False
    if str(payload.get("uia_record_id") or "") != str(uia_record_id):
        return False
    if uia_hash and str(payload.get("uia_content_hash") or "") != str(uia_hash):
        return False
    if not str(payload.get("source_record_id") or "").strip():
        return False
    if not str(payload.get("hwnd") or "").strip():
        return False
    if "window_title" not in payload or not isinstance(payload.get("window_title"), str):
        return False
    if _safe_int(payload.get("window_pid")) <= 0:
        return False
    return _valid_bboxes(payload.get("bboxes"))


def _window_rows(rows: list[dict[str, Any]], *, gap_seconds: int) -> list[dict[str, Any]]:
    ordered = [row for row in rows if isinstance(row, dict) and isinstance(row.get("ts_obj"), datetime)]
    ordered.sort(key=lambda row: (row["ts_obj"], str(row.get("frame_id") or "")))
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in ordered:
        ts = row["ts_obj"]
        if current is None:
            current = {
                "start_utc": ts.isoformat().replace("+00:00", "Z"),
                "end_utc": ts.isoformat().replace("+00:00", "Z"),
                "frame_count": 1,
                "first_frame_id": str(row.get("frame_id") or ""),
                "last_frame_id": str(row.get("frame_id") or ""),
                "last_ts": ts,
            }
            continue
        delta_s = float((ts - current["last_ts"]).total_seconds())
        if delta_s <= float(max(0, int(gap_seconds))):
            current["end_utc"] = ts.isoformat().replace("+00:00", "Z")
            current["frame_count"] = int(current.get("frame_count", 0) or 0) + 1
            current["last_frame_id"] = str(row.get("frame_id") or "")
            current["last_ts"] = ts
            continue
        windows.append(current)
        current = {
            "start_utc": ts.isoformat().replace("+00:00", "Z"),
            "end_utc": ts.isoformat().replace("+00:00", "Z"),
            "frame_count": 1,
            "first_frame_id": str(row.get("frame_id") or ""),
            "last_frame_id": str(row.get("frame_id") or ""),
            "last_ts": ts,
        }
    if current is not None:
        windows.append(current)
    out: list[dict[str, Any]] = []
    for row in windows:
        start = _parse_ts_utc(row.get("start_utc"))
        end = _parse_ts_utc(row.get("end_utc"))
        duration_s = 0.0
        if start is not None and end is not None:
            duration_s = max(0.0, float((end - start).total_seconds()))
        out.append(
            {
                "start_utc": str(row.get("start_utc") or ""),
                "end_utc": str(row.get("end_utc") or ""),
                "duration_s": float(round(duration_s, 3)),
                "frame_count": int(row.get("frame_count", 0) or 0),
                "first_frame_id": str(row.get("first_frame_id") or ""),
                "last_frame_id": str(row.get("last_frame_id") or ""),
            }
        )
    return out


def run_audit(
    db_path: Path,
    *,
    derived_db_path: Path | None = None,
    gap_seconds: int = 120,
    sample_limit: int = 10,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
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
                derived_conn.close()
                derived_conn = None

        counts: dict[str, int] = {}
        for record_type in ("evidence.capture.frame", "evidence.uia.snapshot"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE record_type = ?", (record_type,)).fetchone()
            counts[record_type] = int(row[0]) if row else 0
        for record_type in ("obs.uia.focus", "obs.uia.context", "obs.uia.operable", "derived.ingest.stage1.complete", "retention.eligible"):
            read_conn = derived_conn if derived_conn is not None else conn
            read_table = derived_table if derived_conn is not None and derived_table else table
            row = read_conn.execute(f"SELECT COUNT(*) FROM {read_table} WHERE record_type = ?", (record_type,)).fetchone()
            counts[record_type] = int(row[0]) if row else 0

        rows: list[dict[str, Any]] = []
        issue_counts: dict[str, int] = {}
        plugin_ok_counts: dict[str, int] = {
            "stage1_complete": 0,
            "retention_eligible": 0,
            "uia_snapshot": 0,
            "obs_uia_focus": 0,
            "obs_uia_context": 0,
            "obs_uia_operable": 0,
        }
        plugin_required_counts: dict[str, int] = {key: 0 for key in plugin_ok_counts}
        sample_blocked: list[dict[str, Any]] = []

        sql = f"SELECT {id_col}, {payload_col} FROM {table} WHERE record_type = ? ORDER BY {id_col}"
        for row in conn.execute(sql, ("evidence.capture.frame",)):
            frame_id = str(row[id_col] or "")
            frame = _parse_payload(row[payload_col]) or {}
            ts_utc = str(frame.get("ts_utc") or "")
            ts_obj = _parse_ts_utc(ts_utc)

            issues: list[str] = []
            uia_ref = frame.get("uia_ref") if isinstance(frame.get("uia_ref"), dict) else {}
            uia_record_id = str(uia_ref.get("record_id") or "").strip()
            uia_hash = str(uia_ref.get("content_hash") or "").strip()

            plugin_required_counts["stage1_complete"] += 1
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
            if stage1_type == "derived.ingest.stage1.complete" and isinstance(stage1_payload, dict) and bool(stage1_payload.get("complete", False)):
                plugin_ok_counts["stage1_complete"] += 1
            else:
                issues.append("stage1_complete_missing_or_invalid")

            plugin_required_counts["retention_eligible"] += 1
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
            retention_ok = (
                retention_type == "retention.eligible"
                and isinstance(retention_payload, dict)
                and bool(retention_payload.get("stage1_contract_validated", False))
                and not bool(retention_payload.get("quarantine_pending", False))
            )
            if retention_ok:
                plugin_ok_counts["retention_eligible"] += 1
            else:
                issues.append("retention_eligible_missing_or_invalid")

            if uia_record_id:
                plugin_required_counts["uia_snapshot"] += 1
                snap_type, _snap_payload = _fetch_row(
                    conn,
                    table=table,
                    id_col=id_col,
                    payload_col=payload_col,
                    record_id=uia_record_id,
                )
                if snap_type == "evidence.uia.snapshot":
                    plugin_ok_counts["uia_snapshot"] += 1
                else:
                    issues.append("uia_snapshot_missing")

                obs_expected = _frame_uia_expected_ids(uia_record_id)
                for key, kind in (
                    ("obs_uia_focus", "obs.uia.focus"),
                    ("obs_uia_context", "obs.uia.context"),
                    ("obs_uia_operable", "obs.uia.operable"),
                ):
                    plugin_required_counts[key] += 1
                    obs_id = obs_expected.get(kind, "")
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
                    if obs_type == kind and _obs_payload_ok(obs_payload, kind=kind, uia_record_id=uia_record_id, uia_hash=uia_hash):
                        plugin_ok_counts[key] += 1
                    else:
                        issues.append(f"{key}_missing_or_invalid")

            for issue in issues:
                issue_counts[str(issue)] = int(issue_counts.get(str(issue), 0) or 0) + 1
            queryable = len(issues) == 0
            frame_row = {
                "frame_id": frame_id,
                "ts_utc": ts_utc,
                "ts_obj": ts_obj,
                "queryable": bool(queryable),
                "issues": issues,
                "uia_record_id": uia_record_id,
            }
            rows.append(frame_row)
            if (not queryable) and len(sample_blocked) < max(0, int(sample_limit)):
                sample_blocked.append(
                    {
                        "frame_id": frame_id,
                        "ts_utc": ts_utc,
                        "uia_record_id": uia_record_id,
                        "issues": issues,
                    }
                )

        queryable_rows = [row for row in rows if bool(row.get("queryable", False))]
        windows = _window_rows(queryable_rows, gap_seconds=int(gap_seconds))
        return {
            "ok": True,
            "schema_version": 1,
            "db": str(db_path),
            "derived_db": str(derived_db_path) if isinstance(derived_db_path, Path) else "",
            "summary": {
                "frames_total": int(len(rows)),
                "frames_queryable": int(len(queryable_rows)),
                "frames_blocked": int(max(0, len(rows) - len(queryable_rows))),
                "contiguous_queryable_windows": int(len(windows)),
            },
            "record_counts": counts,
            "plugin_completion": {
                key: {
                    "ok": int(plugin_ok_counts.get(key, 0) or 0),
                    "required": int(plugin_required_counts.get(key, 0) or 0),
                }
                for key in sorted(plugin_ok_counts)
            },
            "issue_counts": issue_counts,
            "queryable_windows": windows,
            "sample_blocked_frames": sample_blocked,
        }
    finally:
        if derived_conn is not None:
            derived_conn.close()
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Stage1 completeness and queryable frame windows.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata DB.")
    parser.add_argument(
        "--derived-db",
        default="",
        help="Optional stage1 derived DB path (default: <db dir>/derived/stage1_derived.db if present).",
    )
    parser.add_argument("--gap-seconds", type=int, default=120, help="Max intra-window timestamp gap in seconds.")
    parser.add_argument("--samples", type=int, default=10, help="Blocked frame samples to emit.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    if not db_path.exists():
        payload = {"ok": False, "error": "db_not_found", "db": str(db_path)}
        print(json.dumps(payload, sort_keys=True))
        return 2
    derived_db: Path | None = None
    raw_derived = str(args.derived_db or "").strip()
    if raw_derived:
        derived_db = Path(raw_derived).expanduser()
    else:
        candidate = default_stage1_derived_db_path(db_path.parent)
        if candidate.exists():
            derived_db = candidate
    try:
        payload = run_audit(
            db_path,
            derived_db_path=derived_db,
            gap_seconds=int(args.gap_seconds),
            sample_limit=int(args.samples),
        )
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(db_path)}
        print(json.dumps(payload, sort_keys=True))
        return 1
    out = str(args.output or "").strip()
    if out:
        out_path = Path(out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 3


if __name__ == "__main__":
    raise SystemExit(main())
