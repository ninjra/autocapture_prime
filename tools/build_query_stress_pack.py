#!/usr/bin/env python3
"""Build deterministic 100-case stress pack from existing query corpora."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SOURCES = [
    "docs/query_eval_cases_generic20.json",
    "docs/query_eval_cases_advanced20.json",
    "docs/query_eval_cases_stage2_time40.json",
    "docs/query_eval_cases_temporal_screenshot_qa_40.json",
    "docs/query_eval_cases_temporal_screenshot_qa_40_additional_grounded.json",
    "docs/query_eval_cases_popup_regression.json",
]


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("cases", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _extract_query(row: dict[str, Any]) -> str:
    return str(row.get("query") or row.get("question") or "").strip()


def build_pack(*, sources: list[Path], target_count: int) -> dict[str, Any]:
    seed_rows: list[dict[str, Any]] = []
    for source in sources:
        for row in _load_cases(source):
            query = _extract_query(row)
            if not query:
                continue
            seed_rows.append(
                {
                    "query": query,
                    "source": str(source),
                    "source_case_id": str(row.get("id") or ""),
                }
            )
    if not seed_rows:
        raise RuntimeError("no_queries_loaded_from_sources")

    cases: list[dict[str, Any]] = []
    cursor = 0
    while len(cases) < int(target_count):
        item = seed_rows[cursor % len(seed_rows)]
        idx = len(cases) + 1
        replay = int(cursor // len(seed_rows))
        case_id = f"STRESS_{idx:03d}"
        case: dict[str, Any] = {
            "id": case_id,
            "query": str(item.get("query") or ""),
            "source_file": str(item.get("source") or ""),
            "source_case_id": str(item.get("source_case_id") or ""),
        }
        if replay > 0:
            case["replay_pass"] = int(replay + 1)
        cases.append(case)
        cursor += 1

    return {
        "schema_version": 1,
        "record_type": "derived.eval.query_stress_pack",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target_count": int(target_count),
        "source_files": [str(path) for path in sources],
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic 100-case stress pack.")
    parser.add_argument("--source", action="append", default=[], help="Source query case file (repeatable).")
    parser.add_argument("--target-count", type=int, default=100)
    parser.add_argument("--out", default="docs/query_eval_cases_stress100.json")
    args = parser.parse_args(argv)

    source_values = [str(x).strip() for x in args.source if str(x).strip()]
    if not source_values:
        source_values = list(DEFAULT_SOURCES)
    sources = [Path(value).expanduser() for value in source_values]
    for source in sources:
        if not source.exists():
            print(json.dumps({"ok": False, "error": "source_not_found", "path": str(source)}, sort_keys=True))
            return 2

    payload = build_pack(sources=sources, target_count=max(1, int(args.target_count)))
    out_path = Path(str(args.out)).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path.resolve()),
                "target_count": int(payload.get("target_count", 0) or 0),
                "actual_count": int(len(payload.get("cases", []) if isinstance(payload.get("cases", []), list) else [])),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
