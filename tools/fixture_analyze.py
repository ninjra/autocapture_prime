"""Analyze fixture report and emit a machine-readable summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _get(obj: Any, *path: str, default=None):
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key, default)
    return cur


def analyze(report_path: Path) -> dict[str, Any]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    queries = payload.get("queries", {}) if isinstance(payload.get("queries", {}), dict) else {}
    idle = payload.get("idle", {}) if isinstance(payload.get("idle", {}), dict) else {}
    stats = idle.get("stats", {}) if isinstance(idle.get("stats", {}), dict) else {}
    ocr = payload.get("ocr", {}) if isinstance(payload.get("ocr", {}), dict) else {}

    query_count = int(queries.get("count", 0) or 0)
    query_failures = int(queries.get("failures", 0) or 0)
    sst_tokens = int(stats.get("sst_tokens", 0) or 0)
    state_spans = int(stats.get("state_spans", 0) or 0)
    state_errors = int(stats.get("state_errors", 0) or 0)
    ocr_backend = str(ocr.get("selected_backend") or "")

    status = "unknown"
    if query_count and query_failures == 0:
        status = "ok"
    elif query_count == 0:
        status = "no_queries"
    elif ocr_backend == "basic" and sst_tokens == 0:
        status = "ocr_missing"
    elif state_spans == 0:
        status = "state_empty"
    else:
        status = "no_evidence"

    return {
        "status": status,
        "query_count": query_count,
        "query_failures": query_failures,
        "sst_tokens": sst_tokens,
        "state_spans": state_spans,
        "state_errors": state_errors,
        "ocr_backend": ocr_backend,
        "idle_done": bool(idle.get("done")),
        "idle_steps": int(idle.get("steps", 0) or 0),
        "run_id": _get(payload, "run_id", default=""),
        "run_dir": _get(payload, "run_dir", default=""),
    }


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if not args:
        print("ERROR: report path required")
        return 2
    report_path = Path(args[0])
    if not report_path.exists():
        print("ERROR: report not found")
        return 2
    summary = analyze(report_path)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
