#!/usr/bin/env python3
"""Fail-closed strict Q40 gate.

Passes only when:
- evaluated == expected_evaluated (default 40)
- skipped == expected_skipped (default 0)
- failed == expected_failed (default 0)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def extract_counts(payload: dict[str, Any]) -> dict[str, int | None]:
    evaluated = _to_int(payload.get("evaluated_total"))
    skipped = _to_int(payload.get("rows_skipped"))
    failed = _to_int(payload.get("evaluated_failed"))

    if evaluated is None and skipped is None and failed is None:
        evaluated = _to_int(payload.get("matrix_evaluated"))
        skipped = _to_int(payload.get("matrix_skipped"))
        failed = _to_int(payload.get("matrix_failed"))

    if evaluated is None and isinstance(payload.get("summary"), dict):
        summary = payload.get("summary", {})
        if isinstance(summary, dict):
            evaluated = _to_int(summary.get("evaluated_total"))
            skipped = _to_int(summary.get("rows_skipped"))
            failed = _to_int(summary.get("evaluated_failed"))

    return {
        "evaluated": evaluated,
        "skipped": skipped,
        "failed": failed,
    }


def evaluate_strict(
    *,
    counts: dict[str, int | None],
    expected_evaluated: int,
    expected_skipped: int,
    expected_failed: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    evaluated = counts.get("evaluated")
    skipped = counts.get("skipped")
    failed = counts.get("failed")
    if evaluated is None:
        reasons.append("evaluated_missing")
    elif int(evaluated) != int(expected_evaluated):
        reasons.append("evaluated_mismatch")
    if skipped is None:
        reasons.append("skipped_missing")
    elif int(skipped) != int(expected_skipped):
        reasons.append("skipped_mismatch")
    if failed is None:
        reasons.append("failed_missing")
    elif int(failed) != int(expected_failed):
        reasons.append("failed_mismatch")
    return len(reasons) == 0, reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate strict Q40 summary metrics.")
    parser.add_argument("--report", required=True, help="Path to Q40 report JSON.")
    parser.add_argument("--output", default="artifacts/q40/gate_q40_strict.json")
    parser.add_argument("--expected-evaluated", type=int, default=40)
    parser.add_argument("--expected-skipped", type=int, default=0)
    parser.add_argument("--expected-failed", type=int, default=0)
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("report must be a JSON object")

    counts = extract_counts(payload)
    ok, reasons = evaluate_strict(
        counts=counts,
        expected_evaluated=int(args.expected_evaluated),
        expected_skipped=int(args.expected_skipped),
        expected_failed=int(args.expected_failed),
    )

    out = {
        "schema_version": 1,
        "ok": bool(ok),
        "report": str(report_path.resolve()),
        "counts": counts,
        "expected": {
            "evaluated": int(args.expected_evaluated),
            "skipped": int(args.expected_skipped),
            "failed": int(args.expected_failed),
        },
        "failure_reasons": reasons,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(ok), "output": str(output_path.resolve())}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
