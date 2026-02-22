#!/usr/bin/env python3
"""Offline queryability repair from normalized DB layers only.

This command is idempotent and does not read raw media. It repairs:
- obs.uia.* documents from frame.uia_ref + evidence.uia.snapshot
- derived.ingest.stage1.complete markers
- retention.eligible markers
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import mark_stage1_and_retention
from autocapture.storage.stage1 import stage1_complete_record_id
from autocapture_nx.ingest.handoff_ingest import _SqliteMetadataAdapter
from autocapture_nx.ingest.handoff_ingest import _choose_source_table
from autocapture_nx.ingest.handoff_ingest import _table_columns
from autocapture_nx.kernel.sqlite_reads import open_sqlite_reader
from autocapture_nx.storage.stage1_derived_store import Stage1DerivedSqliteStore
from autocapture_nx.storage.stage1_derived_store import default_stage1_derived_db_path


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_tool_module(path: str, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable_to_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ReadWriteOverlay:
    """Read-through overlay: reads source DB, writes to stage1_derived DB."""

    def __init__(self, *, read_adapter: Any, write_adapter: Any) -> None:
        self._read = read_adapter
        self._write = write_adapter

    def get(self, record_id: str, default: Any = None) -> Any:
        row = self._write.get(record_id, None)
        if isinstance(row, dict):
            return row
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


def _decode_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return dict(value) if isinstance(value, dict) else None


def _backfill_stage1_and_retention(
    *,
    db_path: Path,
    derived_db_path: Path,
    reason: str,
    limit: int | None = None,
) -> dict[str, Any]:
    source_conn, source_read = open_sqlite_reader(
        db_path,
        prefer_snapshot=True,
        force_snapshot=False,
    )
    summary: dict[str, Any] = {
        "ok": True,
        "source_read": str(source_read),
        "source_table": "",
        "scanned_frames": 0,
        "invalid_payload_frames": 0,
        "stage1_before": 0,
        "stage1_after": 0,
        "stage1_inserted": 0,
        "retention_before": 0,
        "retention_after": 0,
        "retention_inserted": 0,
        "retention_missing_after": 0,
        "retention_validated_after": 0,
    }
    try:
        table = _choose_source_table(source_conn)
        cols = set(_table_columns(source_conn, table))
        payload_col = "payload" if "payload" in cols else ("payload_json" if "payload_json" in cols else "")
        id_col = "id" if "id" in cols else ("record_id" if "record_id" in cols else "")
        if not payload_col or not id_col:
            raise RuntimeError("unsupported_source_table_columns")
        summary["source_table"] = str(table)

        read_adapter = _SqliteMetadataAdapter(source_conn, table, cols)
        write_store = Stage1DerivedSqliteStore(derived_db_path)
        metadata = _ReadWriteOverlay(read_adapter=read_adapter, write_adapter=write_store)

        sql = f"SELECT {id_col}, {payload_col} FROM {table} WHERE record_type = ? ORDER BY {id_col}"
        params: list[Any] = ["evidence.capture.frame"]
        if isinstance(limit, int) and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        for row in source_conn.execute(sql, tuple(params)):
            summary["scanned_frames"] = int(summary.get("scanned_frames", 0) or 0) + 1
            frame_id = str(row[id_col] or "")
            payload = _decode_payload(row[payload_col])
            if not frame_id or not isinstance(payload, dict):
                summary["invalid_payload_frames"] = int(summary.get("invalid_payload_frames", 0) or 0) + 1
                continue

            stage1_id = stage1_complete_record_id(frame_id)
            retention_id = retention_eligibility_record_id(frame_id)
            stage1_before = isinstance(metadata.get(stage1_id, None), dict)
            retention_before = isinstance(metadata.get(retention_id, None), dict)
            if stage1_before:
                summary["stage1_before"] = int(summary.get("stage1_before", 0) or 0) + 1
            if retention_before:
                summary["retention_before"] = int(summary.get("retention_before", 0) or 0) + 1

            mark_stage1_and_retention(
                metadata,
                frame_id,
                payload,
                ts_utc=str(payload.get("ts_utc") or ""),
                reason=reason,
            )

            stage1_after_payload = metadata.get(stage1_id, None)
            retention_after_payload = metadata.get(retention_id, None)
            stage1_after = isinstance(stage1_after_payload, dict) and str(stage1_after_payload.get("record_type") or "") == "derived.ingest.stage1.complete"
            retention_after = isinstance(retention_after_payload, dict) and str(retention_after_payload.get("record_type") or "") == "retention.eligible"
            if stage1_after:
                summary["stage1_after"] = int(summary.get("stage1_after", 0) or 0) + 1
            if retention_after:
                summary["retention_after"] = int(summary.get("retention_after", 0) or 0) + 1
            if stage1_after and (not stage1_before):
                summary["stage1_inserted"] = int(summary.get("stage1_inserted", 0) or 0) + 1
            if retention_after and (not retention_before):
                summary["retention_inserted"] = int(summary.get("retention_inserted", 0) or 0) + 1
            if not retention_after:
                summary["retention_missing_after"] = int(summary.get("retention_missing_after", 0) or 0) + 1
            if retention_after and isinstance(retention_after_payload, dict) and bool(retention_after_payload.get("stage1_contract_validated", False)):
                summary["retention_validated_after"] = int(summary.get("retention_validated_after", 0) or 0) + 1
    finally:
        source_conn.close()
    return summary


def _queryable_ratio(payload: dict[str, Any]) -> float:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
    total = int(summary.get("frames_total", 0) or 0)
    queryable = int(summary.get("frames_queryable", 0) or 0)
    if total <= 0:
        return 0.0
    return float(queryable) / float(total)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    pre = payload.get("pre_audit", {}) if isinstance(payload.get("pre_audit", {}), dict) else {}
    post = payload.get("post_audit", {}) if isinstance(payload.get("post_audit", {}), dict) else {}
    pre_summary = pre.get("summary", {}) if isinstance(pre.get("summary", {}), dict) else {}
    post_summary = post.get("summary", {}) if isinstance(post.get("summary", {}), dict) else {}
    lines: list[str] = []
    lines.append("# Offline Queryability Repair")
    lines.append("")
    lines.append(f"- ok: `{bool(payload.get('ok', False))}`")
    lines.append(f"- db_resolved: `{payload.get('db_resolved', '')}`")
    lines.append(f"- derived_db: `{payload.get('derived_db', '')}`")
    lines.append(f"- failure_reasons: `{','.join([str(x) for x in payload.get('failure_reasons', [])])}`")
    lines.append("")
    lines.append("## Queryability")
    lines.append("")
    lines.append(f"- pre_frames_total: `{int(pre_summary.get('frames_total', 0) or 0)}`")
    lines.append(f"- pre_frames_queryable: `{int(pre_summary.get('frames_queryable', 0) or 0)}`")
    lines.append(f"- pre_queryable_ratio: `{round(float(payload.get('pre_queryable_ratio', 0.0) or 0.0), 6)}`")
    lines.append(f"- post_frames_total: `{int(post_summary.get('frames_total', 0) or 0)}`")
    lines.append(f"- post_frames_queryable: `{int(post_summary.get('frames_queryable', 0) or 0)}`")
    lines.append(f"- post_queryable_ratio: `{round(float(payload.get('post_queryable_ratio', 0.0) or 0.0), 6)}`")
    lines.append(f"- required_min_queryable_ratio: `{round(float(payload.get('required_min_queryable_ratio', 0.0) or 0.0), 6)}`")
    lines.append("")
    lines.append("## Steps")
    lines.append("")
    lines.append(f"- backfill_uia_obs: `{payload.get('backfill_uia_obs', {})}`")
    lines.append(f"- backfill_stage1_retention: `{payload.get('backfill_stage1_retention', {})}`")
    lines.append(f"- revalidate_stage1_markers: `{payload.get('revalidate_stage1_markers', {})}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair Stage1/Stage2 queryability using normalized DB records only.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db")
    parser.add_argument("--derived-db", default="")
    parser.add_argument("--dataroot", default="/mnt/d/autocapture")
    parser.add_argument("--reason", default="offline_queryability_repair")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--wait-stable-seconds", type=float, default=0.0)
    parser.add_argument("--wait-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--poll-interval-ms", type=int, default=250)
    parser.add_argument("--min-queryable-ratio", type=float, default=0.0)
    parser.add_argument("--out", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args(argv)

    audit_mod = _load_tool_module("tools/soak/stage1_completeness_audit.py", "stage1_completeness_audit_tool")
    backfill_mod = _load_tool_module("tools/migrations/backfill_uia_obs_docs.py", "backfill_uia_obs_docs_tool")
    revalidate_mod = _load_tool_module("tools/migrations/revalidate_stage1_markers.py", "revalidate_stage1_markers_tool")

    requested_db = Path(str(args.db)).expanduser()
    resolved_db, resolved_reason = audit_mod._resolve_db_path(requested_db)  # noqa: SLF001
    if not resolved_db.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(resolved_db)}, sort_keys=True))
        return 2

    explicit_derived = str(args.derived_db).strip()
    derived_db = Path(explicit_derived).expanduser() if explicit_derived else default_stage1_derived_db_path(resolved_db.parent)
    wait_summary: dict[str, Any] | None = None
    if float(args.wait_stable_seconds) > 0.0:
        wait_summary = backfill_mod.wait_for_db_stability(
            db_path=resolved_db,
            stable_seconds=float(args.wait_stable_seconds),
            timeout_seconds=float(args.wait_timeout_seconds),
            poll_interval_seconds=max(0.01, float(args.poll_interval_ms) / 1000.0),
        )
        if not bool(wait_summary.get("stable", False)):
            payload = {
                "ok": False,
                "error": "metadata_db_unstable",
                "db": str(resolved_db),
                "wait": wait_summary,
            }
            print(json.dumps(payload, sort_keys=True))
            return 3

    pre_audit = audit_mod.run_audit(
        resolved_db,
        derived_db_path=derived_db if derived_db.exists() else None,
        gap_seconds=int(args.gap_seconds),
        sample_limit=int(args.samples),
        frame_report_limit=int(args.frame_limit),
    )
    backfill_uia = backfill_mod.backfill_uia_obs_docs(
        resolved_db,
        dataroot=str(args.dataroot),
        derived_db_path=derived_db,
        dry_run=False,
        limit=int(args.limit) if int(args.limit) > 0 else None,
        snapshot_read=True,
    )
    backfill_stage1_retention = _backfill_stage1_and_retention(
        db_path=resolved_db,
        derived_db_path=derived_db,
        reason=str(args.reason),
        limit=int(args.limit) if int(args.limit) > 0 else None,
    )
    revalidate_summary = revalidate_mod.revalidate_stage1_markers(
        derived_db,
        source_db_path=resolved_db,
        dry_run=False,
        limit=int(args.limit) if int(args.limit) > 0 else None,
    )
    post_audit = audit_mod.run_audit(
        resolved_db,
        derived_db_path=derived_db,
        gap_seconds=int(args.gap_seconds),
        sample_limit=int(args.samples),
        frame_report_limit=int(args.frame_limit),
    )

    min_ratio = float(max(0.0, min(float(args.min_queryable_ratio), 1.0)))
    pre_ratio = _queryable_ratio(pre_audit)
    post_ratio = _queryable_ratio(post_audit)
    fail_reasons: list[str] = []
    if min_ratio > 0.0 and post_ratio < min_ratio:
        fail_reasons.append("queryable_ratio_below_threshold")

    out_dir = Path("artifacts/queryability_repair") / _utc_stamp()
    out_json = Path(str(args.out).strip()) if str(args.out).strip() else out_dir / "offline_queryability_repair.json"
    out_md = Path(str(args.out_md).strip()) if str(args.out_md).strip() else out_dir / "offline_queryability_repair.md"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "ok": len(fail_reasons) == 0,
        "failure_reasons": fail_reasons,
        "db_requested": str(requested_db),
        "db_resolved": str(resolved_db),
        "db_resolution": str(resolved_reason),
        "derived_db": str(derived_db),
        "wait": wait_summary or {},
        "required_min_queryable_ratio": float(min_ratio),
        "pre_queryable_ratio": float(pre_ratio),
        "post_queryable_ratio": float(post_ratio),
        "pre_audit": pre_audit,
        "backfill_uia_obs": backfill_uia,
        "backfill_stage1_retention": backfill_stage1_retention,
        "revalidate_stage1_markers": revalidate_summary,
        "post_audit": post_audit,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, payload)
    print(
        json.dumps(
            {
                "ok": bool(payload.get("ok", False)),
                "out_json": str(out_json.resolve()),
                "out_md": str(out_md.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

