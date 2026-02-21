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
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids
from autocapture_nx.ingest.uia_obs_docs import _uia_extract_snapshot_dict
from autocapture_nx.ingest.uia_obs_docs import _ensure_frame_uia_docs
from autocapture_nx.kernel.sqlite_reads import open_sqlite_reader


def _decode_payload(payload_text: str | None) -> dict[str, Any] | None:
    if not isinstance(payload_text, str) or not payload_text.strip():
        return None
    try:
        payload = json.loads(payload_text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


class _ReadWriteMetadataAdapter:
    """Read-through adapter: writes to live DB, reads fallback from snapshot."""

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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _assess_frame_uia_docs(
    metadata: Any,
    *,
    source_record_id: str,
    record: dict[str, Any],
    dataroot: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"required": False, "ok": True, "inserted": 0, "reason": "invalid_record"}
    if str(record.get("record_type") or "") != "evidence.capture.frame":
        return {"required": False, "ok": True, "inserted": 0, "reason": "not_frame"}
    uia_ref = record.get("uia_ref") if isinstance(record.get("uia_ref"), dict) else {}
    uia_record_id = str(uia_ref.get("record_id") or "").strip()
    if not uia_record_id:
        return {"required": False, "ok": True, "inserted": 0, "reason": "missing_uia_ref"}

    expected_ids = _frame_uia_expected_ids(uia_record_id)
    existing = {
        record_type: isinstance(metadata.get(doc_id, None), dict)
        and str((metadata.get(doc_id, None) or {}).get("record_type") or "") == str(record_type)
        for record_type, doc_id in expected_ids.items()
    }
    if all(existing.values()):
        return {"required": True, "ok": True, "inserted": 0, "reason": "already_present"}

    snapshot_value = metadata.get(uia_record_id, None)
    snapshot = _uia_extract_snapshot_dict(snapshot_value)
    if not isinstance(snapshot, dict):
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_missing"}
    if str(snapshot.get("record_type") or "").strip() not in {"", "evidence.uia.snapshot"}:
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_record_type_invalid"}

    try:
        from plugins.builtin.processing_sst_uia_context.plugin import _parse_settings as _uia_parse_settings
        from plugins.builtin.processing_sst_uia_context.plugin import _snapshot_to_docs as _uia_snapshot_to_docs
    except Exception:
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_plugin_unavailable"}

    width = max(1, _safe_int(record.get("width") or record.get("frame_width") or 0, default=1))
    height = max(1, _safe_int(record.get("height") or record.get("frame_height") or 0, default=1))
    docs = _uia_snapshot_to_docs(
        plugin_id="builtin.processing.sst.uia_context",
        frame_width=int(width),
        frame_height=int(height),
        uia_ref=uia_ref,
        snapshot=snapshot,
        cfg=_uia_parse_settings({"dataroot": str(dataroot)}),
    )
    if not docs:
        return {"required": True, "ok": False, "inserted": 0, "reason": "snapshot_to_docs_empty"}
    missing = 0
    for record_type, doc_id in expected_ids.items():
        row = metadata.get(doc_id, None)
        if not (isinstance(row, dict) and str(row.get("record_type") or "") == str(record_type)):
            missing += 1
    return {"required": True, "ok": True, "inserted": int(missing), "reason": "dry_run_would_insert"}


def backfill_uia_obs_docs(
    db_path: Path,
    *,
    dataroot: str,
    dry_run: bool = False,
    limit: int | None = None,
    snapshot_read: bool = True,
) -> dict[str, Any]:
    source_conn, source_read = open_sqlite_reader(
        db_path,
        prefer_snapshot=bool(snapshot_read),
        force_snapshot=False,
    )
    conn: sqlite3.Connection | None = None
    write_mode = "dry_run_no_write" if dry_run else "live"
    if not dry_run:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
    summary = {
        "scanned_frames": 0,
        "required_frames": 0,
        "ok_frames": 0,
        "missing_frames": 0,
        "inserted_docs": 0,
        "invalid_payload_frames": 0,
        "source_read": source_read,
        "write_mode": write_mode,
    }
    try:
        source_table = _choose_source_table(source_conn)
        summary["source_table"] = str(source_table)
        source_cols = set(_table_columns(source_conn, source_table))
        payload_col = "payload" if "payload" in source_cols else ("payload_json" if "payload_json" in source_cols else "")
        if not payload_col:
            raise RuntimeError("metadata payload column not found")
        id_col = "id" if "id" in source_cols else ("record_id" if "record_id" in source_cols else "")
        if not id_col:
            raise RuntimeError("metadata id column not found")
        read_adapter = _SqliteMetadataAdapter(source_conn, source_table, source_cols)
        metadata: Any = read_adapter
        if not dry_run:
            if conn is None:
                raise RuntimeError("write_connection_missing")
            write_table = _choose_source_table(conn)
            write_cols = set(_table_columns(conn, write_table))
            write_adapter = _SqliteMetadataAdapter(conn, write_table, write_cols)
            metadata = _ReadWriteMetadataAdapter(read_adapter=read_adapter, write_adapter=write_adapter)

        sql = f"SELECT {id_col}, {payload_col} FROM {source_table} WHERE record_type = ? ORDER BY {id_col}"
        params: list[Any] = ["evidence.capture.frame"]
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        if conn is not None:
            conn.execute("BEGIN")
        for row in source_conn.execute(sql, tuple(params)):
            summary["scanned_frames"] += 1
            record_id = str(row[id_col] or "")
            payload = _decode_payload(row[payload_col])
            if not isinstance(payload, dict):
                summary["invalid_payload_frames"] += 1
                continue
            if dry_run:
                status = _assess_frame_uia_docs(
                    metadata,
                    source_record_id=record_id,
                    record=payload,
                    dataroot=dataroot,
                )
            else:
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
        if conn is not None:
            conn.commit()
    finally:
        source_conn.close()
        if conn is not None:
            conn.close()
    return summary


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill obs.uia.* docs from frame uia_ref + evidence.uia.snapshot.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata.db")
    parser.add_argument("--dataroot", default="/mnt/d/autocapture", help="Autocapture data root")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and rollback without writing")
    parser.add_argument("--limit", type=int, default=0, help="Optional max frame rows to scan (0 = all)")
    parser.add_argument("--snapshot-read", dest="snapshot_read", action="store_true", help="Allow direct read with snapshot fallback.")
    parser.add_argument("--no-snapshot-read", dest="snapshot_read", action="store_false", help="Disable snapshot fallback and read DB directly.")
    parser.set_defaults(snapshot_read=True)
    parser.add_argument("--wait-stable-seconds", type=float, default=0.0, help="Wait until metadata.db is unchanged for this duration.")
    parser.add_argument("--wait-timeout-seconds", type=float, default=0.0, help="Max wait budget for --wait-stable-seconds (0 = no timeout).")
    parser.add_argument("--poll-interval-ms", type=int, default=250, help="Polling interval for stability wait.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(db_path)}))
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
        summary = backfill_uia_obs_docs(
            db_path=db_path,
            dataroot=str(args.dataroot),
            dry_run=bool(args.dry_run),
            limit=int(args.limit) if int(args.limit) > 0 else None,
            snapshot_read=bool(args.snapshot_read),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{exc}", "db": str(db_path)}))
        return 1
    out: dict[str, Any] = {"ok": True, "db": str(db_path), "dry_run": bool(args.dry_run), **summary}
    if isinstance(wait_summary, dict):
        out["wait"] = wait_summary
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
