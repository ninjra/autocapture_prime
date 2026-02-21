#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from autocapture.storage.stage1 import stage1_complete_record_id


def _load_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _resolve_table(conn: sqlite3.Connection) -> tuple[str, str, str, str, str, str]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "metadata" in tables:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
        if {"id", "record_type", "payload"}.issubset(cols):
            return "metadata", "id", "record_type", "payload", ("ts_utc" if "ts_utc" in cols else ""), ("run_id" if "run_id" in cols else "")
    if "records" in tables:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(records)").fetchall()}
        if {"id", "record_type", "json"}.issubset(cols):
            return "records", "id", "record_type", "json", ("ts_utc" if "ts_utc" in cols else ""), ("run_id" if "run_id" in cols else "")
    raise RuntimeError("no_supported_metadata_table")


def _is_frame_source(source_record_id: str, source_record_type: str) -> bool:
    source_type = str(source_record_type or "").strip()
    if source_type:
        return source_type == "evidence.capture.frame"
    source_id = str(source_record_id or "").strip()
    if not source_id:
        return False
    return "/evidence.capture.frame/" in source_id


def _fetch_payload(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_col: str,
    payload_col: str,
    record_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT {payload_col} FROM {table} WHERE {id_col} = ?", (str(record_id),)).fetchone()
    if not row:
        return None
    return _load_payload(row[0] if row else None)


def _is_stage1_complete(stage1_payload: dict[str, Any] | None, source_record_id: str) -> bool:
    if not isinstance(stage1_payload, dict):
        return False
    if str(stage1_payload.get("record_type") or "") != "derived.ingest.stage1.complete":
        return False
    if not bool(stage1_payload.get("complete", False)):
        return False
    if str(stage1_payload.get("source_record_id") or "") != str(source_record_id or ""):
        return False
    return True


def _insert_or_ignore_payload(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_col: str,
    record_type_col: str,
    payload_col: str,
    ts_col: str,
    run_id_col: str,
    record_id: str,
    payload: dict[str, Any],
) -> bool:
    cols = [id_col, record_type_col, payload_col]
    vals: list[Any] = [str(record_id), str(payload.get("record_type") or ""), json.dumps(payload, sort_keys=True)]
    if ts_col:
        cols.append(ts_col)
        vals.append(str(payload.get("ts_utc") or ""))
    if run_id_col:
        cols.append(run_id_col)
        vals.append(str(payload.get("run_id") or ""))
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
    cur = conn.execute(sql, tuple(vals))
    return int(cur.rowcount or 0) > 0


def _seed_from_source(
    *,
    source_conn: sqlite3.Connection,
    source_table: str,
    source_id_col: str,
    source_record_type_col: str,
    source_payload_col: str,
    target_conn: sqlite3.Connection,
    target_table: str,
    target_id_col: str,
    target_record_type_col: str,
    target_payload_col: str,
    target_ts_col: str,
    target_run_id_col: str,
) -> dict[str, int]:
    seeded_stage1 = 0
    seeded_retention = 0
    for record_type in ("derived.ingest.stage1.complete", "retention.eligible"):
        rows = source_conn.execute(
            f"SELECT {source_id_col}, {source_payload_col} FROM {source_table} WHERE {source_record_type_col} = ?",
            (record_type,),
        ).fetchall()
        for row in rows:
            record_id = str(row[0] or "")
            payload = _load_payload(row[1])
            if not record_id or not isinstance(payload, dict):
                continue
            inserted = _insert_or_ignore_payload(
                target_conn,
                table=target_table,
                id_col=target_id_col,
                record_type_col=target_record_type_col,
                payload_col=target_payload_col,
                ts_col=target_ts_col,
                run_id_col=target_run_id_col,
                record_id=record_id,
                payload=payload,
            )
            if not inserted:
                continue
            if record_type == "derived.ingest.stage1.complete":
                seeded_stage1 += 1
            else:
                seeded_retention += 1
    return {"seeded_stage1": int(seeded_stage1), "seeded_retention": int(seeded_retention)}


def revalidate_stage1_markers(
    target_db_path: Path,
    *,
    source_db_path: Path | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    target_conn = sqlite3.connect(str(target_db_path))
    target_conn.row_factory = sqlite3.Row
    source_conn = target_conn
    close_source = False
    summary = {
        "scanned": 0,
        "frame_markers": 0,
        "updated": 0,
        "validated_ready": 0,
        "quarantined": 0,
        "malformed_markers": 0,
        "missing_source": 0,
        "non_frame_skipped": 0,
        "seeded_stage1": 0,
        "seeded_retention": 0,
    }
    try:
        target_table, target_id_col, target_record_type_col, target_payload_col, target_ts_col, target_run_id_col = _resolve_table(target_conn)
        source_table = target_table
        source_id_col = target_id_col
        source_record_type_col = target_record_type_col
        source_payload_col = target_payload_col
        if isinstance(source_db_path, Path) and source_db_path.resolve() != target_db_path.resolve():
            source_conn = sqlite3.connect(str(source_db_path))
            source_conn.row_factory = sqlite3.Row
            close_source = True
            source_table, source_id_col, source_record_type_col, source_payload_col, _src_ts_col, _src_run_col = _resolve_table(source_conn)
            if not dry_run:
                seeded = _seed_from_source(
                    source_conn=source_conn,
                    source_table=source_table,
                    source_id_col=source_id_col,
                    source_record_type_col=source_record_type_col,
                    source_payload_col=source_payload_col,
                    target_conn=target_conn,
                    target_table=target_table,
                    target_id_col=target_id_col,
                    target_record_type_col=target_record_type_col,
                    target_payload_col=target_payload_col,
                    target_ts_col=target_ts_col,
                    target_run_id_col=target_run_id_col,
                )
                summary.update(seeded)

        sql = f"SELECT {target_id_col}, {target_payload_col} FROM {target_table} WHERE {target_record_type_col} = ? ORDER BY {target_id_col}"
        params: list[Any] = ["retention.eligible"]
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = target_conn.execute(sql, tuple(params)).fetchall()
        for row in rows:
            summary["scanned"] += 1
            marker_id = str(row[0] or "")
            marker = _load_payload(row[1])
            if not isinstance(marker, dict):
                summary["malformed_markers"] += 1
                continue
            source_record_id = str(marker.get("source_record_id") or "").strip()
            if not source_record_id:
                summary["missing_source"] += 1
                continue
            source_record_type = str(marker.get("source_record_type") or "").strip()
            if not _is_frame_source(source_record_id, source_record_type):
                summary["non_frame_skipped"] += 1
                continue
            summary["frame_markers"] += 1
            stage1_id = stage1_complete_record_id(source_record_id)
            stage1_payload = _fetch_payload(
                target_conn,
                table=target_table,
                id_col=target_id_col,
                payload_col=target_payload_col,
                record_id=stage1_id,
            )
            if stage1_payload is None and source_conn is not target_conn:
                stage1_payload = _fetch_payload(
                    source_conn,
                    table=source_table,
                    id_col=source_id_col,
                    payload_col=source_payload_col,
                    record_id=stage1_id,
                )
            is_complete = _is_stage1_complete(stage1_payload, source_record_id)

            desired_validated = bool(is_complete)
            desired_quarantine = not bool(is_complete)
            current_validated = bool(marker.get("stage1_contract_validated", False))
            current_quarantine = bool(marker.get("quarantine_pending", False))
            if current_validated == desired_validated and current_quarantine == desired_quarantine:
                if desired_validated:
                    summary["validated_ready"] += 1
                else:
                    summary["quarantined"] += 1
                continue

            marker["schema_version"] = int(marker.get("schema_version") or 1)
            marker["stage1_contract_validated"] = desired_validated
            marker["quarantine_pending"] = desired_quarantine
            if desired_validated:
                marker["eligible"] = True

            if not dry_run:
                update_cols = [(target_payload_col, json.dumps(marker, sort_keys=True)), (target_record_type_col, str(marker.get("record_type") or "retention.eligible"))]
                if target_ts_col:
                    update_cols.append((target_ts_col, str(marker.get("ts_utc") or "")))
                if target_run_id_col:
                    update_cols.append((target_run_id_col, str(marker.get("run_id") or "")))
                assigns = ", ".join(f"{col} = ?" for col, _val in update_cols)
                vals = [val for _col, val in update_cols]
                vals.append(marker_id)
                target_conn.execute(f"UPDATE {target_table} SET {assigns} WHERE {target_id_col} = ?", tuple(vals))
            summary["updated"] += 1
            if desired_validated:
                summary["validated_ready"] += 1
            else:
                summary["quarantined"] += 1
        if not dry_run:
            target_conn.commit()
    finally:
        if close_source and source_conn is not None:
            source_conn.close()
        target_conn.close()
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Revalidate retention.eligible frame markers against Stage1 completeness.")
    parser.add_argument("--db", default="data/metadata.db", help="Path to metadata.db")
    parser.add_argument("--derived-db", default="", help="Optional stage1 derived DB path (retention/stage1 markers location).")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing updates")
    parser.add_argument("--limit", type=int, default=0, help="Optional max markers to scan (0 = all)")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    source_db_path = Path(str(args.db)).expanduser()
    target_db_path = Path(str(args.derived_db)).expanduser() if str(args.derived_db or "").strip() else source_db_path
    if not source_db_path.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(source_db_path)}))
        return 2
    if not target_db_path.exists() and target_db_path != source_db_path:
        target_db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        summary = revalidate_stage1_markers(
            target_db_path,
            source_db_path=source_db_path,
            dry_run=bool(args.dry_run),
            limit=int(args.limit) if int(args.limit) > 0 else None,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(target_db_path), "source_db": str(source_db_path)}))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "db": str(target_db_path),
                "source_db": str(source_db_path),
                "dry_run": bool(args.dry_run),
                **summary,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
