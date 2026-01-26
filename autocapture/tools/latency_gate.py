"""Latency gate validates performance thresholds are defined."""

from __future__ import annotations

import json
from pathlib import Path


def run() -> dict:
    issues: list[str] = []
    config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
    perf = config.get("performance", {})
    for key in ("startup_ms", "query_latency_ms", "ingestion_mb_s"):
        val = perf.get(key)
        if val is None:
            issues.append(f"missing:{key}")
            continue
        if isinstance(val, (int, float)) and val <= 0:
            issues.append(f"non_positive:{key}")
    runtime = config.get("runtime", {})
    for key in ("active_window_s", "idle_window_s"):
        val = runtime.get(key)
        if val is None:
            issues.append(f"missing:{key}")
            continue
        if isinstance(val, (int, float)) and val <= 0:
            issues.append(f"non_positive:{key}")
    return {"ok": len(issues) == 0, "issues": issues}
