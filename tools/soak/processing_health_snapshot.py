#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
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
    latest_manifest_ts: datetime | None = None
    for row in scoped:
        if not isinstance(row, dict):
            continue
        ts_text = str(row.get("ts_utc") or "").strip()
        if ts_text:
            parsed: datetime | None = None
            try:
                parsed = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
            except Exception:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                else:
                    parsed = parsed.astimezone(timezone.utc)
                if latest_manifest_ts is None or parsed > latest_manifest_ts:
                    latest_manifest_ts = parsed
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
    freshness_lag_hours = None
    if latest_manifest_ts is not None:
        freshness_lag_hours = max(0.0, round((datetime.now(timezone.utc) - latest_manifest_ts).total_seconds() / 3600.0, 6))

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
        "schema_version": 2,
        "samples": int(len(scoped)),
        "latest": {
            "pending_records": int(latest_pending),
            "completed_records": int(latest_completed),
            "throughput_records_per_s": float(latest_throughput),
            "projected_lag_hours": float(latest_lag),
            "manifest_ts_utc": latest_manifest_ts.isoformat().replace("+00:00", "Z") if latest_manifest_ts is not None else "",
            "manifest_freshness_lag_hours": freshness_lag_hours,
        },
        "events": {
            "retention_risk": int(retention_risk_events),
            "metadata_db_unstable": int(metadata_db_unstable_events),
            "throughput_zero_with_backlog": int(throughput_zero_backlog_events),
        },
        "alerts": alerts,
    }


def probe_db_freshness(db_path: Path) -> dict[str, Any]:
    """Probe metadata DB directly for capture and stage1 timestamps."""
    import sqlite3
    result: dict[str, Any] = {
        "db_path": str(db_path),
        "db_exists": bool(db_path.exists()),
        "latest_capture_ts_utc": None,
        "latest_stage1_complete_ts_utc": None,
        "freshness_lag_hours": None,
    }
    if not db_path.exists():
        return result
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        conn.execute("PRAGMA query_only = ON")
        for record_type, key in (
            ("evidence.capture.frame", "latest_capture_ts_utc"),
            ("derived.ingest.stage1.complete", "latest_stage1_complete_ts_utc"),
        ):
            row = conn.execute(
                "SELECT MAX(ts_utc) FROM metadata WHERE record_type = ?",
                (record_type,),
            ).fetchone()
            raw_ts = str(row[0] or "").strip() if row else ""
            if raw_ts:
                result[key] = raw_ts
        # Compute freshness lag from latest stage1 timestamp
        stage1_ts = str(result.get("latest_stage1_complete_ts_utc") or "").strip()
        if stage1_ts:
            try:
                parsed = datetime.fromisoformat(stage1_ts.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                else:
                    parsed = parsed.astimezone(timezone.utc)
                lag = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0)
                result["freshness_lag_hours"] = round(lag, 6)
            except Exception:
                pass
    except Exception as exc:
        result["db_error"] = f"{type(exc).__name__}:{exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return result


def resolve_manifests_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if text:
        return Path(text).expanduser()
    preferred = Path("/mnt/d/autocapture/facts/landscape_manifests.ndjson")
    legacy = Path("/mnt/d/autocapture/landscape_manifests.ndjson")
    return preferred if preferred.exists() else legacy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize processing health from landscape manifests NDJSON.")
    parser.add_argument(
        "--manifests",
        default="",
        help="Path to landscape manifests NDJSON (default resolves to /mnt/d/autocapture/facts/landscape_manifests.ndjson).",
    )
    parser.add_argument("--tail", type=int, default=30, help="How many latest rows to include.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument(
        "--db",
        default="",
        help="Optional metadata DB path to probe for freshness (e.g. /mnt/d/autocapture/metadata.live.db).",
    )
    parser.add_argument("--max-freshness-lag-hours", type=float, default=24.0, help="Freshness SLO threshold in hours.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    path = resolve_manifests_path(str(args.manifests or ""))
    rows = _load_ndjson(path)
    payload = build_health_snapshot(rows, tail=int(args.tail))
    payload["manifests_path"] = str(path)
    payload["exists"] = bool(path.exists())

    # DB-sourced freshness probe
    db_path_str = str(args.db or "").strip()
    if db_path_str:
        db_freshness = probe_db_freshness(Path(db_path_str))
        payload["db_freshness"] = db_freshness
    else:
        # Auto-detect: try derived DB, then live DB, then primary
        for candidate in (
            Path("/mnt/d/autocapture/derived/stage1_derived.db"),
            Path("/mnt/d/autocapture/metadata.live.db"),
            Path("/mnt/d/autocapture/metadata.db"),
        ):
            if candidate.exists():
                db_freshness = probe_db_freshness(candidate)
                payload["db_freshness"] = db_freshness
                break

    # Freshness SLO check
    max_lag = float(args.max_freshness_lag_hours)
    db_freshness_data = payload.get("db_freshness", {}) if isinstance(payload.get("db_freshness"), dict) else {}
    db_lag = db_freshness_data.get("freshness_lag_hours")
    if isinstance(db_lag, (int, float)):
        freshness_ok = float(db_lag) <= max_lag
        payload["freshness_ok"] = bool(freshness_ok)
        payload["freshness_lag_hours"] = float(db_lag)
        payload["max_freshness_lag_hours"] = float(max_lag)
        if not freshness_ok:
            alerts = payload.get("alerts", []) if isinstance(payload.get("alerts"), list) else []
            if "freshness_lag_exceeded" not in alerts:
                alerts.append("freshness_lag_exceeded")
                payload["alerts"] = alerts

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
