#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def build_health_snapshot(rows: list[dict[str, Any]], *, tail: int = 30) -> dict[str, Any]:
    scoped = rows[-max(1, int(tail)) :] if rows else []
    pending_series: list[int] = []
    completed_series: list[int] = []
    throughput_series: list[float] = []
    lag_series: list[float] = []
    retention_risk_events = 0
    metadata_db_unstable_events = 0
    throughput_zero_backlog_events = 0
    for row in scoped:
        if not isinstance(row, dict):
            continue
        sla = row.get("sla") if isinstance(row.get("sla"), dict) else {}
        pending_series.append(int(sla.get("pending_records", 0) or 0))
        completed_series.append(int(sla.get("completed_records", 0) or 0))
        try:
            throughput_series.append(float(sla.get("throughput_records_per_s", 0.0) or 0.0))
        except Exception:
            throughput_series.append(0.0)
        try:
            lag_series.append(float(sla.get("projected_lag_hours", 0.0) or 0.0))
        except Exception:
            lag_series.append(float("inf"))
        if bool(sla.get("retention_risk", False)):
            retention_risk_events += 1
        guard = row.get("metadata_db_guard") if isinstance(row.get("metadata_db_guard"), dict) else {}
        if guard and not bool(guard.get("ok", True)):
            metadata_db_unstable_events += 1
        slo_alerts = [str(x) for x in (row.get("slo_alerts") or []) if str(x)]
        if "throughput_zero_with_backlog" in slo_alerts:
            throughput_zero_backlog_events += 1

    latest_pending = pending_series[-1] if pending_series else 0
    latest_completed = completed_series[-1] if completed_series else 0
    latest_throughput = throughput_series[-1] if throughput_series else 0.0
    latest_lag = lag_series[-1] if lag_series else 0.0

    alerts: list[str] = []
    if retention_risk_events > 0:
        alerts.append("retention_risk")
    if metadata_db_unstable_events > 0:
        alerts.append("metadata_db_unstable")
    if latest_pending > 0 and latest_throughput <= 0.0:
        alerts.append("throughput_zero_with_backlog")
    elif throughput_zero_backlog_events > 0:
        alerts.append("throughput_zero_with_backlog")

    return {
        "ok": True,
        "schema_version": 1,
        "samples": int(len(scoped)),
        "latest": {
            "pending_records": int(latest_pending),
            "completed_records": int(latest_completed),
            "throughput_records_per_s": float(latest_throughput),
            "projected_lag_hours": float(latest_lag),
        },
        "events": {
            "retention_risk": int(retention_risk_events),
            "metadata_db_unstable": int(metadata_db_unstable_events),
            "throughput_zero_with_backlog": int(throughput_zero_backlog_events),
        },
        "alerts": alerts,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize processing health from landscape manifests NDJSON.")
    parser.add_argument("--manifests", default="/mnt/d/autocapture/landscape_manifests.ndjson", help="Path to landscape manifests NDJSON.")
    parser.add_argument("--tail", type=int, default=30, help="How many latest rows to include.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    path = Path(str(args.manifests)).expanduser()
    rows = _load_ndjson(path)
    payload = build_health_snapshot(rows, tail=int(args.tail))
    payload["manifests_path"] = str(path)
    payload["exists"] = bool(path.exists())
    out = str(args.output or "").strip()
    if out:
        out_path = Path(out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
