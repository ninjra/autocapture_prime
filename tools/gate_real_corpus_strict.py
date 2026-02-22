#!/usr/bin/env python3
"""Fail-closed strict gate for real-corpus readiness reports."""

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
    return {
        "total": _to_int(payload.get("matrix_total")),
        "evaluated": _to_int(payload.get("matrix_evaluated")),
        "skipped": _to_int(payload.get("matrix_skipped")),
        "failed": _to_int(payload.get("matrix_failed")),
    }


def evaluate_strict(*, counts: dict[str, int | None], expected_total: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    total = counts.get("total")
    evaluated = counts.get("evaluated")
    skipped = counts.get("skipped")
    failed = counts.get("failed")
    if total is None:
        reasons.append("total_missing")
    elif int(total) != int(expected_total):
        reasons.append("total_mismatch")
    if evaluated is None:
        reasons.append("evaluated_missing")
    elif int(evaluated) != int(expected_total):
        reasons.append("evaluated_mismatch")
    if skipped is None:
        reasons.append("skipped_missing")
    elif int(skipped) != 0:
        reasons.append("skipped_nonzero")
    if failed is None:
        reasons.append("failed_missing")
    elif int(failed) != 0:
        reasons.append("failed_nonzero")
    return len(reasons) == 0, reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate strict real-corpus summary metrics.")
    parser.add_argument("--report", required=True, help="Path to real-corpus readiness report JSON.")
    parser.add_argument("--output", default="artifacts/real_corpus/gate_real_corpus_strict.json")
    parser.add_argument("--expected-total", type=int, default=20)
    args = parser.parse_args(argv)

    report_path = Path(str(args.report))
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("report must be a JSON object")
    counts = extract_counts(payload)
    ok, reasons = evaluate_strict(counts=counts, expected_total=int(args.expected_total))
    report_ok = bool(payload.get("ok", True))
    report_reasons = payload.get("failure_reasons", []) if isinstance(payload.get("failure_reasons", []), list) else []
    if not report_ok:
        reasons.append("report_ok_false")
    if report_reasons:
        reasons.append("report_failure_reasons_nonempty")
    ok = bool(ok and report_ok and len(report_reasons) == 0)
    out = {
        "schema_version": 1,
        "ok": bool(ok),
        "report": str(report_path.resolve()),
        "counts": counts,
        "expected_total": int(args.expected_total),
        "failure_reasons": reasons,
    }
    output_path = Path(str(args.output))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(ok), "output": str(output_path.resolve())}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
