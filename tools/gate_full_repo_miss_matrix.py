#!/usr/bin/env python3
"""Gate: fail closed when full-repo miss inventory reports actionable rows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from autocapture_nx.kernel.paths import resolve_repo_path


def _run_refresh(repo_root: Path) -> int:
    script = repo_root / "tools" / "run_full_repo_miss_refresh.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
    return int(proc.returncode)


def _load_inventory(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _summary_counts(payload: dict) -> tuple[int, int]:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    rows = int(summary.get("rows_total", 0) or 0)
    gate_failures = int(summary.get("gate_failures_total", 0) or 0)
    return rows, gate_failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Run tools/run_full_repo_miss_refresh.sh before evaluation.")
    parser.add_argument(
        "--inventory-json",
        default="artifacts/repo_miss_inventory/latest.json",
        help="Inventory json emitted by tools/full_repo_miss_inventory.py",
    )
    args = parser.parse_args(argv)

    repo_root = resolve_repo_path(".")
    if args.refresh:
        rc = _run_refresh(repo_root)
        if rc != 0:
            print(f"FAIL: full-repo miss refresh failed (exit={rc})")
            return 2

    inv_path = resolve_repo_path(args.inventory_json)
    if not inv_path.exists():
        print(f"FAIL: inventory json missing: {inv_path}")
        return 2

    payload = _load_inventory(inv_path)
    rows_total, gate_failures_total = _summary_counts(payload)
    if rows_total > 0 or gate_failures_total > 0:
        print(
            "FAIL: full-repo miss matrix gate "
            f"(rows_total={rows_total}, gate_failures_total={gate_failures_total})"
        )
        return 1

    print("OK: full-repo miss matrix gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
