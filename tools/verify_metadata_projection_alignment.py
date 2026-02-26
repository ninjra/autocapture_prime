#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_TYPES: tuple[str, ...] = (
    "evidence.capture.frame",
    "derived.ingest.stage1.complete",
    "retention.eligible",
    "derived.ingest.stage2.complete",
    "derived.sst.state",
    "derived.sst.text.extra",
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?",
        (str(name),),
    ).fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _count_by_type(conn: sqlite3.Connection, table: str, record_type: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE record_type = ?",
        (str(record_type),),
    ).fetchone()
    return int(row[0]) if row else 0


def evaluate_alignment(*, db_path: Path, record_types: list[str]) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "metadata"):
            return {
                "ok": False,
                "error": "metadata_table_missing",
                "db": str(db_path),
                "rows": [],
            }
        if not _table_exists(conn, "metadata_projection"):
            return {
                "ok": False,
                "error": "metadata_projection_table_missing",
                "db": str(db_path),
                "rows": [],
            }
        rows: list[dict[str, Any]] = []
        mismatch_count = 0
        for record_type in record_types:
            source_count = _count_by_type(conn, "metadata", record_type)
            projection_count = _count_by_type(conn, "metadata_projection", record_type)
            delta = int(source_count) - int(projection_count)
            row = {
                "record_type": str(record_type),
                "metadata_count": int(source_count),
                "projection_count": int(projection_count),
                "delta": int(delta),
                "match": bool(delta == 0),
            }
            if delta != 0:
                mismatch_count += 1
            rows.append(row)
        return {
            "ok": mismatch_count == 0,
            "error": "",
            "db": str(db_path),
            "rows": rows,
            "mismatch_count": int(mismatch_count),
        }
    except sqlite3.DatabaseError as exc:
        return {
            "ok": False,
            "error": f"database_error:{type(exc).__name__}:{exc}",
            "db": str(db_path),
            "rows": [],
            "mismatch_count": 0,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify metadata_projection alignment against metadata.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db")
    parser.add_argument("--record-type", action="append", dest="record_types", default=[])
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    db_path = Path(str(args.db)).expanduser()
    record_types = [str(x).strip() for x in list(args.record_types or []) if str(x).strip()]
    if not record_types:
        record_types = list(DEFAULT_TYPES)

    payload = evaluate_alignment(db_path=db_path, record_types=record_types)
    if str(args.output).strip():
        out = Path(str(args.output)).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
