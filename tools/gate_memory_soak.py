#!/usr/bin/env python3
"""Fail-closed gate for memory soak stability artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = payload.get(key, default)
    try:
        if raw is None:
            return float(default)
        value = float(raw)
        if math.isnan(value) or math.isinf(value):
            return float(default)
        return value
    except Exception:
        return float(default)


def _as_int(payload: dict[str, Any], key: str, default: int = 0) -> int:
    raw = payload.get(key, default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def evaluate_memory_soak(
    summary: dict[str, Any],
    *,
    min_loops: int,
    max_rss_delta_mb: float,
    max_rss_tail_span_mb: float,
    max_promptops_service_cache_entries: int,
    max_query_fast_cache_entries: int,
    max_p95_ms: float,
) -> tuple[bool, list[str], dict[str, Any]]:
    loops = _as_int(summary, "loops", 0)
    rss_delta_mb = _as_float(summary, "rss_delta_mb", default=0.0)
    rss_tail_span_mb = _as_float(summary, "rss_tail_span_mb", default=0.0)
    promptops_layers_last = _as_int(summary, "promptops_layers_last", 0)
    promptops_apis_last = _as_int(summary, "promptops_apis_last", 0)
    query_fast_cache_last = _as_int(summary, "query_fast_cache_last", 0)
    lat_p95_ms = _as_float(summary, "lat_p95_ms", default=0.0)

    reasons: list[str] = []
    if loops < int(min_loops):
        reasons.append("loops_below_min")
    if rss_delta_mb > float(max_rss_delta_mb):
        reasons.append("rss_delta_exceeds_limit")
    if rss_tail_span_mb > float(max_rss_tail_span_mb):
        reasons.append("rss_tail_span_exceeds_limit")
    if promptops_layers_last > int(max_promptops_service_cache_entries):
        reasons.append("promptops_layers_exceeds_limit")
    if promptops_apis_last > int(max_promptops_service_cache_entries):
        reasons.append("promptops_apis_exceeds_limit")
    if query_fast_cache_last > int(max_query_fast_cache_entries):
        reasons.append("query_fast_cache_exceeds_limit")
    if lat_p95_ms > float(max_p95_ms):
        reasons.append("latency_p95_exceeds_limit")

    observed = {
        "loops": loops,
        "rss_delta_mb": rss_delta_mb,
        "rss_tail_span_mb": rss_tail_span_mb,
        "promptops_layers_last": promptops_layers_last,
        "promptops_apis_last": promptops_apis_last,
        "query_fast_cache_last": query_fast_cache_last,
        "lat_p95_ms": lat_p95_ms,
    }
    return (len(reasons) == 0, reasons, observed)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _coerce_summary(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("summary")
    if isinstance(nested, dict):
        return nested
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed memory soak gate.")
    parser.add_argument(
        "--summary",
        default="artifacts/memory_soak/memory_soak_300_latest.json",
        help="Path to soak summary JSON.",
    )
    parser.add_argument(
        "--out",
        default="artifacts/memory_soak/gate_memory_soak.json",
        help="Output report path.",
    )
    parser.add_argument("--min-loops", type=int, default=200)
    parser.add_argument("--max-rss-delta-mb", type=float, default=8.0)
    parser.add_argument("--max-rss-tail-span-mb", type=float, default=2.0)
    parser.add_argument("--max-promptops-service-cache-entries", type=int, default=16)
    parser.add_argument("--max-query-fast-cache-entries", type=int, default=4096)
    parser.add_argument("--max-p95-ms", type=float, default=2500.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or []))
    summary_path = Path(args.summary)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not summary_path.exists():
        report = {
            "ok": False,
            "reasons": ["summary_missing"],
            "summary": str(summary_path),
            "ts_utc": _now_utc(),
        }
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    summary = _coerce_summary(_load_json(summary_path))
    ok, reasons, observed = evaluate_memory_soak(
        summary,
        min_loops=max(1, int(args.min_loops)),
        max_rss_delta_mb=max(0.0, float(args.max_rss_delta_mb)),
        max_rss_tail_span_mb=max(0.0, float(args.max_rss_tail_span_mb)),
        max_promptops_service_cache_entries=max(1, int(args.max_promptops_service_cache_entries)),
        max_query_fast_cache_entries=max(1, int(args.max_query_fast_cache_entries)),
        max_p95_ms=max(1.0, float(args.max_p95_ms)),
    )
    report = {
        "ok": bool(ok),
        "reasons": reasons,
        "summary": str(summary_path),
        "thresholds": {
            "min_loops": max(1, int(args.min_loops)),
            "max_rss_delta_mb": max(0.0, float(args.max_rss_delta_mb)),
            "max_rss_tail_span_mb": max(0.0, float(args.max_rss_tail_span_mb)),
            "max_promptops_service_cache_entries": max(1, int(args.max_promptops_service_cache_entries)),
            "max_query_fast_cache_entries": max(1, int(args.max_query_fast_cache_entries)),
            "max_p95_ms": max(1.0, float(args.max_p95_ms)),
        },
        "observed": observed,
        "ts_utc": _now_utc(),
    }
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
