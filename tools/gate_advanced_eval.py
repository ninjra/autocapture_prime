#!/usr/bin/env python3
"""Fail-closed gate for advanced Q/H evaluation artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _evaluated_rows(rows: list[dict[str, Any]]) -> tuple[int, int]:
    total = 0
    passed = 0
    for row in rows:
        ev = row.get("expected_eval") if isinstance(row.get("expected_eval"), dict) else {}
        if not bool(ev.get("evaluated", False)):
            continue
        total += 1
        if bool(ev.get("passed", False)):
            passed += 1
    return total, passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, help="Path to advanced eval JSON artifact.")
    parser.add_argument("--require-total", type=int, default=20, help="Required number of rows in artifact.")
    parser.add_argument("--require-evaluated", type=int, default=20, help="Required number of strictly evaluated rows.")
    parser.add_argument("--max-failed", type=int, default=0, help="Maximum allowed failed evaluated rows.")
    args = parser.parse_args(argv)

    artifact = _load(Path(str(args.artifact)).resolve())
    rows_any = artifact.get("rows", [])
    rows = [item for item in rows_any if isinstance(item, dict)] if isinstance(rows_any, list) else []
    rows_total = int(len(rows))
    evaluated_total, evaluated_passed = _evaluated_rows(rows)
    evaluated_failed = max(0, evaluated_total - evaluated_passed)

    checks = {
        "rows_total": rows_total,
        "evaluated_total": evaluated_total,
        "evaluated_passed": evaluated_passed,
        "evaluated_failed": evaluated_failed,
        "require_total": int(args.require_total),
        "require_evaluated": int(args.require_evaluated),
        "max_failed": int(args.max_failed),
    }
    ok = True
    if rows_total < int(args.require_total):
        ok = False
    if evaluated_total < int(args.require_evaluated):
        ok = False
    if evaluated_failed > int(args.max_failed):
        ok = False

    print(json.dumps({"ok": ok, "checks": checks}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

