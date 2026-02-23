#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from autocapture_nx.ingest.handoff_ingest import _SqliteMetadataAdapter
from autocapture_nx.ingest.handoff_ingest import _choose_source_table
from autocapture_nx.ingest.handoff_ingest import _table_columns
from autocapture_nx.ingest.stage2_projection_docs import project_stage2_docs_for_frame
from autocapture_nx.kernel.sqlite_reads import open_sqlite_reader
from autocapture.storage.stage1 import mark_stage2_complete


def _decode_payload(payload_text: str | None) -> dict[str, Any] | None:
    if not isinstance(payload_text, str) or not payload_text.strip():
        return None
    try:
        payload = json.loads(payload_text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


class _ReadWriteAdapter:
    """Read-through adapter: reads snapshot source, writes live DB."""

    def __init__(self, *, read_adapter: Any, write_adapter: Any) -> None:
        self._read = read_adapter
        self._write = write_adapter

    def get(self, record_id: str, default: Any = None) -> Any:
        primary = self._write.get(record_id, None)
        if isinstance(primary, dict):
            return primary
        return self._read.get(record_id, default)

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        self._write.put_new(record_id, value)

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        self._write.put(record_id, value)

    def put_replace(self, record_id: str, value: dict[str, Any]) -> None:
        if hasattr(self._write, "put_replace"):
            self._write.put_replace(record_id, value)
            return
        self._write.put(record_id, value)


def wait_for_db_stability(
    db_path: Path,
    *,
    stable_seconds: float,
    timeout_seconds: float,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    stable_seconds = float(max(0.0, stable_seconds))
    timeout_seconds = float(max(0.0, timeout_seconds))
    poll_interval_seconds = float(max(0.01, poll_interval_seconds))
    start = time.monotonic()
    last_sig: tuple[int, int, int] | None = None
    unchanged_for = 0.0
    samples = 0
    while True:
        if not db_path.exists():
            return {
                "stable": False,
                "reason": "db_not_found",
                "samples": int(samples),
                "waited_seconds": round(time.monotonic() - start, 3),
            }
        try:
            st = os.stat(str(db_path))
            sig = (int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
        except Exception as exc:
            return {
                "stable": False,
                "reason": f"stat_failed:{type(exc).__name__}",
                "samples": int(samples),
                "waited_seconds": round(time.monotonic() - start, 3),
            }
        samples += 1
        if last_sig is not None and sig == last_sig:
            unchanged_for += poll_interval_seconds
        else:
            unchanged_for = 0.0
            last_sig = sig
        elapsed = time.monotonic() - start
        if stable_seconds <= 0.0 or unchanged_for >= stable_seconds:
            return {
                "stable": True,
                "reason": "stable",
                "samples": int(samples),
                "waited_seconds": round(elapsed, 3),
                "signature": {
                    "inode": int(sig[0]),
                    "size": int(sig[1]),
                    "mtime_ns": int(sig[2]),
                },
            }
        if timeout_seconds > 0.0 and elapsed >= timeout_seconds:
            return {
                "stable": False,
                "reason": "timeout",
                "samples": int(samples),
                "waited_seconds": round(elapsed, 3),
                "signature": {
                    "inode": int(sig[0]),
                    "size": int(sig[1]),
                    "mtime_ns": int(sig[2]),
                },
            }
        time.sleep(poll_interval_seconds)


def backfill_stage2_projection_docs(
    db_path: Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    snapshot_read: bool = True,
    mark_stage2: bool = True,
) -> dict[str, Any]:
    source_conn, source_read = open_sqlite_reader(
        db_path,
        prefer_snapshot=bool(snapshot_read),
        force_snapshot=False,
    )
    write_conn: sqlite3.Connection | None = None
    write_mode = "dry_run" if dry_run else "live"
    summary = {
        "source_read": source_read,
        "write_mode": write_mode,
        "source_table": "",
        "scanned_frames": 0,
        "invalid_payload_frames": 0,
        "required_frames": 0,
        "ok_frames": 0,
        "error_frames": 0,
        "generated_docs": 0,
        "inserted_docs": 0,
        "generated_states": 0,
        "inserted_states": 0,
        "stage2_marker_inserted": 0,
        "stage2_marker_complete": 0,
    }
    try:
        source_table = _choose_source_table(source_conn)
        summary["source_table"] = str(source_table)
        source_cols = set(_table_columns(source_conn, source_table))
        payload_col = "payload" if "payload" in source_cols else ("payload_json" if "payload_json" in source_cols else "")
        id_col = "id" if "id" in source_cols else ("record_id" if "record_id" in source_cols else "")
        if not payload_col:
            raise RuntimeError("metadata_payload_column_missing")
        if not id_col:
            raise RuntimeError("metadata_id_column_missing")
        read_adapter = _SqliteMetadataAdapter(source_conn, source_table, source_cols)
        write_store: Any = read_adapter
        if not dry_run:
            write_conn = sqlite3.connect(str(db_path), timeout=5.0)
            write_conn.row_factory = sqlite3.Row
            write_table = _choose_source_table(write_conn)
            write_cols = set(_table_columns(write_conn, write_table))
            write_adapter = _SqliteMetadataAdapter(write_conn, write_table, write_cols)
            write_store = _ReadWriteAdapter(read_adapter=read_adapter, write_adapter=write_adapter)
            write_conn.execute("BEGIN")

        sql = f"SELECT {id_col}, {payload_col} FROM {source_table} WHERE record_type = ? ORDER BY {id_col}"
        params: list[Any] = ["evidence.capture.frame"]
        if isinstance(limit, int) and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        for row in source_conn.execute(sql, tuple(params)):
            summary["scanned_frames"] = int(summary.get("scanned_frames", 0) or 0) + 1
            source_record_id = str(row[id_col] or "")
            payload = _decode_payload(row[payload_col])
            if not source_record_id or not isinstance(payload, dict):
                summary["invalid_payload_frames"] = int(summary.get("invalid_payload_frames", 0) or 0) + 1
                continue
            status = project_stage2_docs_for_frame(
                write_store,
                source_record_id=source_record_id,
                frame_record=payload,
                read_store=read_adapter,
                dry_run=bool(dry_run),
            )
            if bool(status.get("required", False)):
                summary["required_frames"] = int(summary.get("required_frames", 0) or 0) + 1
            if bool(status.get("ok", False)):
                summary["ok_frames"] = int(summary.get("ok_frames", 0) or 0) + 1
            else:
                summary["error_frames"] = int(summary.get("error_frames", 0) or 0) + 1
            summary["generated_docs"] = int(summary.get("generated_docs", 0) or 0) + int(status.get("generated_docs", 0) or 0)
            summary["inserted_docs"] = int(summary.get("inserted_docs", 0) or 0) + int(status.get("inserted_docs", 0) or 0)
            summary["generated_states"] = int(summary.get("generated_states", 0) or 0) + int(status.get("generated_states", 0) or 0)
            summary["inserted_states"] = int(summary.get("inserted_states", 0) or 0) + int(status.get("inserted_states", 0) or 0)
            if (not dry_run) and bool(mark_stage2):
                stage2_id, stage2_inserted = mark_stage2_complete(
                    write_store,
                    source_record_id,
                    payload,
                    projection=status if isinstance(status, dict) else None,
                    reason="stage2_projection_backfill",
                )
                if stage2_inserted:
                    summary["stage2_marker_inserted"] = int(summary.get("stage2_marker_inserted", 0) or 0) + 1
                if stage2_id:
                    marker = write_store.get(stage2_id, {})
                    if isinstance(marker, dict) and bool(marker.get("complete", False)):
                        summary["stage2_marker_complete"] = int(summary.get("stage2_marker_complete", 0) or 0) + 1
        if write_conn is not None:
            write_conn.commit()
    finally:
        source_conn.close()
        if write_conn is not None:
            write_conn.close()
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill derived.sst.text.extra docs from normalized frame/UIA metadata only.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata DB")
    parser.add_argument("--dry-run", action="store_true", help="Analyze without writing")
    parser.add_argument("--limit", type=int, default=0, help="Optional max frame rows to scan (0 = all)")
    parser.add_argument("--snapshot-read", dest="snapshot_read", action="store_true", help="Allow read snapshot fallback.")
    parser.add_argument("--no-snapshot-read", dest="snapshot_read", action="store_false", help="Read DB directly without snapshot fallback.")
    parser.set_defaults(snapshot_read=True)
    parser.add_argument("--mark-stage2", dest="mark_stage2", action="store_true", help="Write derived.ingest.stage2.complete markers.")
    parser.add_argument("--no-mark-stage2", dest="mark_stage2", action="store_false", help="Do not write stage2 completion markers.")
    parser.set_defaults(mark_stage2=True)
    parser.add_argument("--wait-stable-seconds", type=float, default=0.0, help="Wait until metadata DB is unchanged for this duration.")
    parser.add_argument("--wait-timeout-seconds", type=float, default=0.0, help="Max wait budget for --wait-stable-seconds (0 = no timeout).")
    parser.add_argument("--poll-interval-ms", type=int, default=250, help="Polling interval for stability wait.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(db_path)}, sort_keys=True))
        return 2
    wait_summary: dict[str, Any] | None = None
    if float(args.wait_stable_seconds) > 0.0:
        wait_summary = wait_for_db_stability(
            db_path=db_path,
            stable_seconds=float(args.wait_stable_seconds),
            timeout_seconds=float(args.wait_timeout_seconds),
            poll_interval_seconds=max(0.01, float(args.poll_interval_ms) / 1000.0),
        )
        if not bool(wait_summary.get("stable", False)):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "metadata_db_unstable",
                        "db": str(db_path),
                        "wait": wait_summary,
                    },
                    sort_keys=True,
                )
            )
            return 3
    try:
        summary = backfill_stage2_projection_docs(
            db_path=db_path,
            dry_run=bool(args.dry_run),
            limit=int(args.limit) if int(args.limit) > 0 else None,
            snapshot_read=bool(args.snapshot_read),
            mark_stage2=bool(args.mark_stage2),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(db_path)}, sort_keys=True))
        return 1
    out: dict[str, Any] = {"ok": True, "db": str(db_path), "dry_run": bool(args.dry_run), **summary}
    if isinstance(wait_summary, dict):
        out["wait"] = wait_summary
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
