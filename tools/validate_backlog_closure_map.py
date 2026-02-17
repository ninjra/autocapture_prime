#!/usr/bin/env python3
"""Validate backlog closure crosswalk completeness and artifact existence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-json", default="artifacts/repo_miss_inventory/backlog_closure_map_latest.json")
    parser.add_argument("--baseline-json", default="artifacts/repo_miss_inventory/backlog_rows_baseline_2026-02-16.json")
    args = parser.parse_args(argv)

    map_path = ROOT / str(args.map_json)
    base_path = ROOT / str(args.baseline_json)
    if not map_path.exists():
        print(f"FAIL: missing map json: {map_path}")
        return 2
    if not base_path.exists():
        print(f"FAIL: missing baseline json: {base_path}")
        return 2

    mapping = _load(map_path)
    baseline = _load(base_path)
    rows = mapping.get("rows", []) if isinstance(mapping.get("rows"), list) else []
    row_keys = [str(r.get("row_key") or "") for r in rows if isinstance(r, dict)]
    expected_keys = [str(x) for x in (baseline.get("row_keys") or []) if str(x)]

    missing = sorted(set(expected_keys) - set(row_keys))
    extra = sorted(set(row_keys) - set(expected_keys))
    if missing:
        print(f"FAIL: closure map missing row keys: {len(missing)}")
        for key in missing[:20]:
            print(f"  - {key}")
        return 1

    if extra:
        print(f"WARN: closure map has extra row keys: {len(extra)}")

    required_fields = ("row_key", "source_path", "line", "closure_artifacts", "closure_command", "expected_signal")
    bad_rows = 0
    missing_artifacts: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            bad_rows += 1
            continue
        for field in required_fields:
            if field not in row:
                bad_rows += 1
                break
        artifacts = row.get("closure_artifacts", [])
        if not isinstance(artifacts, list) or not artifacts:
            bad_rows += 1
            continue
        for rel in artifacts:
            artifact = ROOT / str(rel)
            if not artifact.exists():
                missing_artifacts.append(str(rel))

    if bad_rows > 0:
        print(f"FAIL: malformed rows in closure map: {bad_rows}")
        return 1
    if missing_artifacts:
        uniq = sorted(set(missing_artifacts))
        print(f"FAIL: missing closure artifacts: {len(uniq)}")
        for rel in uniq[:40]:
            print(f"  - {rel}")
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "rows_total": len(rows),
                "expected_rows_total": len(expected_keys),
                "extra_rows": len(extra),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

