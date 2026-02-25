#!/usr/bin/env python3
"""Fail-closed composite gate for popup + Q40 + Temporal40 strict semantics."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"parse_error:{type(exc).__name__}:{exc}"
    if not isinstance(payload, dict):
        return None, "not_object"
    return payload, ""


def _age_minutes(path: Path) -> float | None:
    try:
        st = path.stat()
    except Exception:
        return None
    age_s = max(0.0, float(time.time() - float(st.st_mtime)))
    return age_s / 60.0


def _extract_counts(payload: dict[str, Any]) -> dict[str, int | None]:
    evaluated = _to_int(payload.get("evaluated_total"))
    skipped = _to_int(payload.get("rows_skipped"))
    failed = _to_int(payload.get("evaluated_failed"))
    if evaluated is None and skipped is None and failed is None:
        evaluated = _to_int(payload.get("matrix_evaluated"))
        skipped = _to_int(payload.get("matrix_skipped"))
        failed = _to_int(payload.get("matrix_failed"))
    counts_obj = payload.get("counts", {})
    if isinstance(counts_obj, dict):
        if evaluated is None:
            evaluated = _to_int(counts_obj.get("evaluated"))
        if skipped is None:
            skipped = _to_int(counts_obj.get("skipped"))
        if failed is None:
            failed = _to_int(counts_obj.get("failed"))
    return {"evaluated": evaluated, "skipped": skipped, "failed": failed}


def _evaluate_counts(
    *,
    name: str,
    counts: dict[str, int | None],
    expected_evaluated: int,
    expected_skipped: int,
    expected_failed: int,
) -> list[str]:
    reasons: list[str] = []
    evaluated = counts.get("evaluated")
    skipped = counts.get("skipped")
    failed = counts.get("failed")
    if evaluated is None:
        reasons.append(f"{name}.evaluated_missing")
    elif int(evaluated) != int(expected_evaluated):
        reasons.append(f"{name}.evaluated_mismatch")
    if skipped is None:
        reasons.append(f"{name}.skipped_missing")
    elif int(skipped) != int(expected_skipped):
        reasons.append(f"{name}.skipped_mismatch")
    if failed is None:
        reasons.append(f"{name}.failed_missing")
    elif int(failed) != int(expected_failed):
        reasons.append(f"{name}.failed_mismatch")
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate popup/Q40/Temporal strict gate bundle.")
    parser.add_argument("--popup-report", default="artifacts/query_acceptance/popup_regression_latest.json")
    parser.add_argument("--q40-report", default="artifacts/advanced10/q40_matrix_latest.json")
    parser.add_argument("--temporal-report", default="artifacts/temporal40/temporal40_gate_latest.json")
    parser.add_argument("--expected-popup-sample", type=int, default=10)
    parser.add_argument("--expected-q40-evaluated", type=int, default=40)
    parser.add_argument("--expected-q40-skipped", type=int, default=0)
    parser.add_argument("--expected-q40-failed", type=int, default=0)
    parser.add_argument("--expected-temporal-evaluated", type=int, default=40)
    parser.add_argument("--expected-temporal-skipped", type=int, default=0)
    parser.add_argument("--expected-temporal-failed", type=int, default=0)
    parser.add_argument("--max-age-minutes", type=float, default=180.0)
    parser.add_argument("--output", default="artifacts/release/gate_golden_pipeline_triplet.json")
    args = parser.parse_args(argv)

    popup_path = Path(str(args.popup_report)).expanduser()
    q40_path = Path(str(args.q40_report)).expanduser()
    temporal_path = Path(str(args.temporal_report)).expanduser()

    reasons: list[str] = []
    ages = {
        "popup": _age_minutes(popup_path),
        "q40": _age_minutes(q40_path),
        "temporal": _age_minutes(temporal_path),
    }
    max_age = float(max(1.0, float(args.max_age_minutes)))
    for key, age in ages.items():
        if age is None:
            reasons.append(f"{key}.artifact_age_missing")
        elif float(age) > max_age:
            reasons.append(f"{key}.artifact_stale")

    popup_payload, popup_err = _load_json(popup_path)
    if popup_payload is None:
        reasons.append(f"popup_report_{popup_err}")
        popup_counts = {"sample_count": None, "accepted_count": None, "failed_count": None}
    else:
        popup_counts = {
            "sample_count": _to_int(popup_payload.get("sample_count")),
            "accepted_count": _to_int(popup_payload.get("accepted_count")),
            "failed_count": _to_int(popup_payload.get("failed_count")),
        }
        if popup_counts["sample_count"] is None:
            reasons.append("popup.sample_count_missing")
        elif int(popup_counts["sample_count"]) != int(args.expected_popup_sample):
            reasons.append("popup.sample_count_mismatch")
        if popup_counts["accepted_count"] is None:
            reasons.append("popup.accepted_count_missing")
        elif int(popup_counts["accepted_count"]) != int(args.expected_popup_sample):
            reasons.append("popup.accepted_count_mismatch")
        if popup_counts["failed_count"] is None:
            reasons.append("popup.failed_count_missing")
        elif int(popup_counts["failed_count"]) != 0:
            reasons.append("popup.failed_count_nonzero")

    q40_payload, q40_err = _load_json(q40_path)
    if q40_payload is None:
        reasons.append(f"q40_report_{q40_err}")
        q40_counts = {"evaluated": None, "skipped": None, "failed": None}
    else:
        q40_counts = _extract_counts(q40_payload)
        reasons.extend(
            _evaluate_counts(
                name="q40",
                counts=q40_counts,
                expected_evaluated=int(args.expected_q40_evaluated),
                expected_skipped=int(args.expected_q40_skipped),
                expected_failed=int(args.expected_q40_failed),
            )
        )

    temporal_payload, temporal_err = _load_json(temporal_path)
    if temporal_payload is None:
        reasons.append(f"temporal_report_{temporal_err}")
        temporal_counts = {"evaluated": None, "skipped": None, "failed": None}
    else:
        temporal_counts = _extract_counts(temporal_payload)
        reasons.extend(
            _evaluate_counts(
                name="temporal",
                counts=temporal_counts,
                expected_evaluated=int(args.expected_temporal_evaluated),
                expected_skipped=int(args.expected_temporal_skipped),
                expected_failed=int(args.expected_temporal_failed),
            )
        )

    ok = len(reasons) == 0
    out = {
        "schema_version": 1,
        "ok": bool(ok),
        "popup_report": str(popup_path.resolve()),
        "q40_report": str(q40_path.resolve()),
        "temporal_report": str(temporal_path.resolve()),
        "counts": {
            "popup": popup_counts,
            "q40": q40_counts,
            "temporal": temporal_counts,
        },
        "artifact_age_minutes": ages,
        "max_age_minutes": max_age,
        "failure_reasons": reasons,
    }

    output_path = Path(str(args.output)).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(ok), "output": str(output_path.resolve())}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
