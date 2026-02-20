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
    if not isinstance(value, dict):
        return None
    return value


def _is_frame_source(source_record_id: str, source_record_type: str) -> bool:
    source_type = str(source_record_type or "").strip()
    if source_type:
        return source_type == "evidence.capture.frame"
    source_id = str(source_record_id or "").strip()
    if not source_id:
        return False
    return "/evidence.capture.frame/" in source_id


def _fetch_payload(conn: sqlite3.Connection, record_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT payload FROM metadata WHERE id = ?", (record_id,)).fetchone()
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


def revalidate_stage1_markers(db_path: Path, *, dry_run: bool = False, limit: int | None = None) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    summary = {
        "scanned": 0,
        "frame_markers": 0,
        "updated": 0,
        "validated_ready": 0,
        "quarantined": 0,
        "malformed_markers": 0,
        "missing_source": 0,
        "non_frame_skipped": 0,
    }
    try:
        sql = "SELECT id, payload FROM metadata WHERE record_type = ? ORDER BY id"
        params: list[Any] = ["retention.eligible"]
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(sql, tuple(params)).fetchall()
        for row in rows:
            summary["scanned"] += 1
            marker_id = str(row["id"] or "")
            marker = _load_payload(row["payload"])
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
            stage1_payload = _fetch_payload(conn, stage1_id)
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
                conn.execute(
                    "UPDATE metadata SET payload = ?, record_type = ?, ts_utc = ?, run_id = ? WHERE id = ?",
                    (
                        json.dumps(marker, sort_keys=True),
                        str(marker.get("record_type") or "retention.eligible"),
                        str(marker.get("ts_utc") or ""),
                        str(marker.get("run_id") or ""),
                        marker_id,
                    ),
                )
            summary["updated"] += 1
            if desired_validated:
                summary["validated_ready"] += 1
            else:
                summary["quarantined"] += 1
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Revalidate retention.eligible frame markers against Stage1 completeness.")
    parser.add_argument("--db", default="data/metadata.db", help="Path to metadata.db")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing updates")
    parser.add_argument("--limit", type=int, default=0, help="Optional max markers to scan (0 = all)")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(db_path)}))
        return 2
    try:
        summary = revalidate_stage1_markers(
            db_path,
            dry_run=bool(args.dry_run),
            limit=int(args.limit) if int(args.limit) > 0 else None,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(db_path)}))
        return 1
    print(json.dumps({"ok": True, "db": str(db_path), "dry_run": bool(args.dry_run), **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
