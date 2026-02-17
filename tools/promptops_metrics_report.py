#!/usr/bin/env python3
"""Aggregate PromptOps metrics into chartable JSON/CSV artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _pct(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    p = max(0.0, min(100.0, float(percentile)))
    data = sorted(float(v) for v in values)
    if len(data) == 1:
        return float(round(data[0], 3))
    pos = (len(data) - 1) * (p / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    weight = pos - lo
    value = data[lo] * (1.0 - weight) + data[hi] * weight
    return float(round(value, 3))


def _safe_float(value: Any) -> float:
    try:
        out = float(value or 0.0)
    except Exception:
        return 0.0
    if out < 0.0:
        return 0.0
    return float(round(out, 6))


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes", "on"}


def _write_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        kind = str(row.get("type") or "unknown")
        by_type.setdefault(kind, []).append(row)

    prep = by_type.get("promptops.prepare_prompt", [])
    model = by_type.get("promptops.model_interaction", [])
    review = by_type.get("promptops.review_result", [])

    prep_lat = [_safe_float(r.get("latency_ms")) for r in prep]
    model_lat = [_safe_float(r.get("latency_ms")) for r in model]
    prep_conf = [_safe_float(r.get("confidence")) for r in prep if r.get("confidence") is not None]

    strategies: dict[str, int] = {}
    for row in prep:
        key = str(row.get("strategy") or "unknown")
        strategies[key] = int(strategies.get(key, 0) + 1)

    model_success = int(sum(1 for r in model if _safe_bool(r.get("success"))))
    model_total = int(len(model))
    review_updated = int(sum(1 for r in review if _safe_bool(r.get("updated"))))
    review_pending = int(sum(1 for r in review if _safe_bool(r.get("pending_approval"))))

    report = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "rows_total": int(len(rows)),
        "type_counts": {k: int(len(v)) for k, v in sorted(by_type.items(), key=lambda kv: kv[0])},
        "prepare_prompt": {
            "count": int(len(prep)),
            "latency_ms_p50": _pct(prep_lat, 50.0),
            "latency_ms_p95": _pct(prep_lat, 95.0),
            "latency_ms_p99": _pct(prep_lat, 99.0),
            "confidence_mean": float(round((sum(prep_conf) / len(prep_conf)), 6)) if prep_conf else 0.0,
            "strategy_counts": {k: int(v) for k, v in sorted(strategies.items(), key=lambda kv: kv[0])},
        },
        "model_interaction": {
            "count": model_total,
            "success_count": model_success,
            "success_rate": float(round((model_success / model_total), 6)) if model_total else 0.0,
            "latency_ms_p50": _pct(model_lat, 50.0),
            "latency_ms_p95": _pct(model_lat, 95.0),
            "latency_ms_p99": _pct(model_lat, 99.0),
        },
        "review": {
            "count": int(len(review)),
            "updated_count": review_updated,
            "pending_approval_count": review_pending,
            "updated_rate": float(round((review_updated / len(review)), 6)) if review else 0.0,
        },
        "recommendations": [],
    }

    recs: list[dict[str, Any]] = []
    prep_p95 = float(report["prepare_prompt"]["latency_ms_p95"])
    model_p95 = float(report["model_interaction"]["latency_ms_p95"])
    if int(len(prep)) >= 25 and prep_p95 > 250.0:
        recs.append(
            {
                "kind": "prepare_prompt_high_latency_p95",
                "reason": f"prepare_prompt p95 is {prep_p95:.3f}ms over 250ms threshold",
            }
        )
    if int(model_total) >= 25 and model_p95 > 4000.0:
        recs.append(
            {
                "kind": "model_interaction_high_latency_p95",
                "reason": f"model_interaction p95 is {model_p95:.3f}ms over 4000ms threshold",
            }
        )
    if model_total >= 10 and float(report["model_interaction"]["success_rate"]) < 0.5:
        recs.append(
            {
                "kind": "model_interaction_low_success_rate",
                "reason": f"model success rate is {report['model_interaction']['success_rate']:.3f}",
            }
        )
    report["recommendations"] = recs
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="data/promptops/metrics.jsonl", help="PromptOps metrics jsonl path")
    parser.add_argument("--out-json", default="artifacts/promptops/metrics_report_latest.json", help="Output JSON report path")
    parser.add_argument("--out-csv", default="artifacts/promptops/metrics_report_latest.csv", help="Output CSV report path")
    args = parser.parse_args(argv)

    metrics_path = Path(str(args.metrics)).resolve()
    rows = _load_jsonl(metrics_path)
    report = build_report(rows)
    report["metrics_path"] = str(metrics_path)

    out_json = Path(str(args.out_json))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    csv_rows = []
    for kind, count in sorted((report.get("type_counts") or {}).items(), key=lambda kv: kv[0]):
        csv_rows.append({"metric": f"type_count.{kind}", "value": int(count)})
    csv_rows.extend(
        [
            {"metric": "prepare_prompt.p50_ms", "value": report["prepare_prompt"]["latency_ms_p50"]},
            {"metric": "prepare_prompt.p95_ms", "value": report["prepare_prompt"]["latency_ms_p95"]},
            {"metric": "model_interaction.p50_ms", "value": report["model_interaction"]["latency_ms_p50"]},
            {"metric": "model_interaction.p95_ms", "value": report["model_interaction"]["latency_ms_p95"]},
            {"metric": "model_interaction.success_rate", "value": report["model_interaction"]["success_rate"]},
            {"metric": "review.updated_rate", "value": report["review"]["updated_rate"]},
        ]
    )
    out_csv = Path(str(args.out_csv))
    _write_csv(out_csv, csv_rows, headers=["metric", "value"])

    print(json.dumps({"ok": True, "rows": int(len(rows)), "json": str(out_json), "csv": str(out_csv)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

