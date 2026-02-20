#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from autocapture_nx.ingest.handoff_ingest import _SqliteMetadataAdapter
from autocapture_nx.ingest.handoff_ingest import _choose_source_table
from autocapture_nx.ingest.handoff_ingest import _table_columns
from autocapture_nx.ingest.uia_obs_docs import _ensure_frame_uia_docs


def _decode_payload(payload_text: str | None) -> dict[str, Any] | None:
    if not isinstance(payload_text, str) or not payload_text.strip():
        return None
    try:
        payload = json.loads(payload_text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def backfill_uia_obs_docs(
    db_path: Path,
    *,
    dataroot: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    summary = {
        "scanned_frames": 0,
        "required_frames": 0,
        "ok_frames": 0,
        "missing_frames": 0,
        "inserted_docs": 0,
        "invalid_payload_frames": 0,
    }
    try:
        table = _choose_source_table(conn)
        cols = set(_table_columns(conn, table))
        metadata = _SqliteMetadataAdapter(conn, table, cols)
        payload_col = "payload" if "payload" in cols else ("payload_json" if "payload_json" in cols else "")
        if not payload_col:
            raise RuntimeError("metadata payload column not found")
        id_col = "id" if "id" in cols else ("record_id" if "record_id" in cols else "")
        if not id_col:
            raise RuntimeError("metadata id column not found")

        sql = f"SELECT {id_col}, {payload_col} FROM {table} WHERE record_type = ? ORDER BY {id_col}"
        params: list[Any] = ["evidence.capture.frame"]
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        conn.execute("BEGIN")
        for row in conn.execute(sql, tuple(params)):
            summary["scanned_frames"] += 1
            record_id = str(row[id_col] or "")
            payload = _decode_payload(row[payload_col])
            if not isinstance(payload, dict):
                summary["invalid_payload_frames"] += 1
                continue
            status = _ensure_frame_uia_docs(
                metadata,
                source_record_id=record_id,
                record=payload,
                dataroot=dataroot,
            )
            summary["inserted_docs"] += int(status.get("inserted", 0) or 0)
            if bool(status.get("required", False)):
                summary["required_frames"] += 1
                if bool(status.get("ok", False)):
                    summary["ok_frames"] += 1
                else:
                    summary["missing_frames"] += 1
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill obs.uia.* docs from frame uia_ref + evidence.uia.snapshot.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata.db")
    parser.add_argument("--dataroot", default="/mnt/d/autocapture", help="Autocapture data root")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and rollback without writing")
    parser.add_argument("--limit", type=int, default=0, help="Optional max frame rows to scan (0 = all)")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(db_path)}))
        return 2
    try:
        summary = backfill_uia_obs_docs(
            db_path=db_path,
            dataroot=str(args.dataroot),
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
