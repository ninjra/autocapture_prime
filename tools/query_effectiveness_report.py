#!/usr/bin/env python3
"""Aggregate query trace + feedback into chartable effectiveness metrics."""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = str(raw or "").strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                out.append(item)
    return out


def _ms(value: Any) -> float:
    try:
        num = float(value or 0.0)
    except Exception:
        return 0.0
    if num < 0.0:
        num = 0.0
    return float(round(num, 3))


def _bp(value: Any) -> int:
    try:
        num = int(value or 0)
    except Exception:
        return 0
    return max(0, min(10000, num))


def _safe_div(a: float, b: float) -> float:
    if b <= 0:
        return 0.0
    return float(a / b)


def _write_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


@dataclass(frozen=True)
class RunRow:
    query_run_id: str
    ts_utc: str
    query: str
    method: str
    winner: str
    answer_state: str
    answer_summary: str
    coverage_bp: int
    latency_total_ms: float
    handoff_count: int
    provider_ids: list[str]
    provider_count: int
    user_score_bp: int | None
    user_verdict: str


def _run_rows(traces: list[dict[str, Any]], feedback_rows: list[dict[str, Any]]) -> list[RunRow]:
    latest_trace: dict[str, dict[str, Any]] = {}
    for row in traces:
        rid = str(row.get("query_run_id") or "").strip()
        if not rid:
            continue
        latest_trace[rid] = row
    latest_feedback: dict[str, dict[str, Any]] = {}
    for row in feedback_rows:
        rid = str(row.get("query_run_id") or "").strip()
        if not rid:
            continue
        latest_feedback[rid] = row
    out: list[RunRow] = []
    for rid, row in latest_trace.items():
        stage_ms = row.get("stage_ms", {}) if isinstance(row.get("stage_ms", {}), dict) else {}
        handoffs = row.get("handoffs", []) if isinstance(row.get("handoffs", []), list) else []
        providers = row.get("providers", []) if isinstance(row.get("providers", []), list) else []
        provider_ids = sorted(
            {
                str(item.get("provider_id") or "").strip()
                for item in providers
                if isinstance(item, dict) and str(item.get("provider_id") or "").strip()
            }
        )
        fb = latest_feedback.get(rid, {})
        score_bp = fb.get("score_bp")
        score_bp_int = _bp(score_bp) if score_bp is not None else None
        out.append(
            RunRow(
                query_run_id=rid,
                ts_utc=str(row.get("ts_utc") or ""),
                query=str(row.get("query") or ""),
                method=str(row.get("method") or ""),
                winner=str(row.get("winner") or ""),
                answer_state=str(row.get("answer_state") or ""),
                answer_summary=str(row.get("answer_summary") or ""),
                coverage_bp=_bp(row.get("coverage_bp")),
                latency_total_ms=_ms(stage_ms.get("total", 0.0)),
                handoff_count=int(len(handoffs)),
                provider_ids=provider_ids,
                provider_count=int(len(provider_ids)),
                user_score_bp=score_bp_int,
                user_verdict=str(fb.get("verdict") or ""),
            )
        )
    out.sort(key=lambda item: (item.ts_utc, item.query_run_id))
    return out


def _provider_stats(
    traces_by_id: dict[str, dict[str, Any]],
    rows: list[RunRow],
    *,
    min_samples: int,
    latency_threshold_ms: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    agg: dict[str, dict[str, Any]] = {}
    quality_samples: list[float] = []
    for row in rows:
        if row.user_score_bp is not None:
            quality_samples.append(float(row.user_score_bp))
        else:
            quality_samples.append(float(row.coverage_bp))
    baseline_quality = _safe_div(sum(quality_samples), float(len(quality_samples))) if quality_samples else 0.0

    for row in rows:
        trace = traces_by_id.get(row.query_run_id, {})
        providers = trace.get("providers", []) if isinstance(trace.get("providers", []), list) else []
        for item in providers:
            if not isinstance(item, dict):
                continue
            provider_id = str(item.get("provider_id") or "").strip()
            if not provider_id:
                continue
            entry = agg.setdefault(
                provider_id,
                {
                    "provider_id": provider_id,
                    "runs_total": 0,
                    "feedback_total": 0,
                    "correct_total": 0,
                    "helped_total": 0,
                    "hurt_total": 0,
                    "neutral_total": 0,
                    "latency_sum_ms": 0.0,
                    "provider_latency_sum_ms": 0.0,
                    "contribution_sum_bp": 0.0,
                    "quality_sum_bp": 0.0,
                    "quality_samples": 0,
                },
            )
            entry["runs_total"] += 1
            entry["latency_sum_ms"] += float(row.latency_total_ms)
            entry["provider_latency_sum_ms"] += _ms(item.get("estimated_latency_ms"))
            entry["contribution_sum_bp"] += float(_bp(item.get("contribution_bp")))
            if row.user_score_bp is not None:
                entry["feedback_total"] += 1
                if int(row.user_score_bp) >= 5000:
                    entry["correct_total"] += 1
                    entry["helped_total"] += 1
                else:
                    entry["hurt_total"] += 1
                entry["quality_sum_bp"] += float(row.user_score_bp)
                entry["quality_samples"] += 1
            else:
                entry["neutral_total"] += 1
                entry["quality_sum_bp"] += float(row.coverage_bp)
                entry["quality_samples"] += 1

    provider_rows: list[dict[str, Any]] = []
    recs: list[dict[str, Any]] = []
    for provider_id, item in sorted(agg.items(), key=lambda kv: kv[0]):
        runs_total = int(item["runs_total"])
        feedback_total = int(item["feedback_total"])
        correct_total = int(item["correct_total"])
        accuracy = _safe_div(float(correct_total), float(feedback_total)) if feedback_total > 0 else 0.0
        mean_latency = _safe_div(float(item["latency_sum_ms"]), float(runs_total))
        mean_provider_latency = _safe_div(float(item["provider_latency_sum_ms"]), float(runs_total))
        mean_contribution_bp = int(round(_safe_div(float(item["contribution_sum_bp"]), float(runs_total))))
        quality_mean_bp = _safe_div(float(item["quality_sum_bp"]), float(item["quality_samples"]))
        confidence_delta_bp = float(round(quality_mean_bp - baseline_quality, 3))
        row = {
            "provider_id": provider_id,
            "runs_total": runs_total,
            "feedback_total": feedback_total,
            "correct_total": correct_total,
            "helped_total": int(item["helped_total"]),
            "hurt_total": int(item["hurt_total"]),
            "neutral_total": int(item["neutral_total"]),
            "accuracy": round(accuracy, 4),
            "mean_run_latency_ms": round(mean_latency, 3),
            "mean_provider_latency_ms": round(mean_provider_latency, 3),
            "mean_contribution_bp": mean_contribution_bp,
            "quality_mean_bp": round(quality_mean_bp, 3),
            "confidence_delta_bp": confidence_delta_bp,
        }
        provider_rows.append(row)

        if feedback_total >= int(min_samples) and accuracy < 0.6:
            if mean_latency >= float(latency_threshold_ms):
                recs.append(
                    {
                        "kind": "provider_low_accuracy_high_latency",
                        "provider_id": provider_id,
                        "reason": f"accuracy={accuracy:.3f} over {feedback_total} feedback runs, mean_latency_ms={mean_latency:.1f}",
                    }
                )
            else:
                recs.append(
                    {
                        "kind": "provider_low_accuracy",
                        "provider_id": provider_id,
                        "reason": f"accuracy={accuracy:.3f} over {feedback_total} feedback runs",
                    }
                )
        if runs_total >= int(min_samples) and confidence_delta_bp < -500.0:
            recs.append(
                {
                    "kind": "provider_negative_confidence_delta",
                    "provider_id": provider_id,
                    "reason": f"confidence_delta_bp={confidence_delta_bp:.1f}, quality_mean_bp={quality_mean_bp:.1f}, baseline_bp={baseline_quality:.1f}",
                }
            )
    return provider_rows, recs


def _sequence_stats(rows: list[RunRow], traces_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        trace = traces_by_id.get(row.query_run_id, {})
        handoffs = trace.get("handoffs", []) if isinstance(trace.get("handoffs", []), list) else []
        seq = []
        seq_ms = 0.0
        for edge in handoffs:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("from") or "").strip()
            dst = str(edge.get("to") or "").strip()
            if not src or not dst:
                continue
            seq.append(f"{src}>{dst}")
            seq_ms += _ms(edge.get("latency_ms", 0.0))
        key = " | ".join(seq) if seq else "none"
        item = agg.setdefault(
            key,
            {
                "sequence": key,
                "runs_total": 0,
                "latency_sum_ms": 0.0,
                "feedback_total": 0,
                "correct_total": 0,
            },
        )
        item["runs_total"] += 1
        item["latency_sum_ms"] += seq_ms
        if row.user_score_bp is not None:
            item["feedback_total"] += 1
            if int(row.user_score_bp) >= 5000:
                item["correct_total"] += 1
    out: list[dict[str, Any]] = []
    for item in agg.values():
        runs_total = int(item["runs_total"])
        feedback_total = int(item["feedback_total"])
        correct_total = int(item["correct_total"])
        accuracy = _safe_div(float(correct_total), float(feedback_total)) if feedback_total > 0 else 0.0
        out.append(
            {
                "sequence": str(item["sequence"]),
                "runs_total": runs_total,
                "feedback_total": feedback_total,
                "correct_total": correct_total,
                "accuracy": round(accuracy, 4),
                "mean_latency_ms": round(_safe_div(float(item["latency_sum_ms"]), float(runs_total)), 3),
            }
        )
    out.sort(key=lambda item: (item["sequence"]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="", help="Data dir containing facts/*.ndjson")
    parser.add_argument("--out-dir", default="artifacts/query_metrics", help="Output report directory")
    parser.add_argument("--min-samples", type=int, default=3, help="Minimum feedback samples for recommendation rules")
    parser.add_argument("--latency-threshold-ms", type=float, default=1500.0, help="High-latency threshold for recommendations")
    args = parser.parse_args(argv)

    data_dir = str(args.data_dir or os.getenv("AUTOCAPTURE_DATA_DIR", "data")).strip()
    root = Path(data_dir)
    facts = root / "facts"
    traces = _load_ndjson(facts / "query_trace.ndjson")
    feedback = _load_ndjson(facts / "query_feedback.ndjson")
    traces_by_id = {str(item.get("query_run_id") or "").strip(): item for item in traces if isinstance(item, dict)}
    rows = _run_rows(traces, feedback)

    provider_rows, recs = _provider_stats(
        traces_by_id,
        rows,
        min_samples=max(1, int(args.min_samples)),
        latency_threshold_ms=float(args.latency_threshold_ms),
    )
    sequence_rows = _sequence_stats(rows, traces_by_id)
    feedback_coverage = int(sum(1 for row in rows if row.user_score_bp is not None))
    no_feedback_count = max(0, len(rows) - feedback_coverage)
    if no_feedback_count > 0:
        recs.append(
            {
                "kind": "missing_feedback",
                "provider_id": "",
                "reason": f"{no_feedback_count} query runs missing reviewer verdicts",
            }
        )

    out_dir = Path(str(args.out_dir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_rows = [
        {
            "query_run_id": row.query_run_id,
            "ts_utc": row.ts_utc,
            "query": row.query,
            "method": row.method,
            "winner": row.winner,
            "answer_state": row.answer_state,
            "answer_summary": row.answer_summary,
            "coverage_bp": row.coverage_bp,
            "latency_total_ms": row.latency_total_ms,
            "handoff_count": row.handoff_count,
            "provider_count": row.provider_count,
            "providers": ",".join(row.provider_ids),
            "user_score_bp": row.user_score_bp if row.user_score_bp is not None else "",
            "user_verdict": row.user_verdict,
        }
        for row in rows
    ]
    _write_csv(
        out_dir / "runs.csv",
        run_rows,
        [
            "query_run_id",
            "ts_utc",
            "query",
            "method",
            "winner",
            "answer_state",
            "answer_summary",
            "coverage_bp",
            "latency_total_ms",
            "handoff_count",
            "provider_count",
            "providers",
            "user_score_bp",
            "user_verdict",
        ],
    )
    _write_csv(
        out_dir / "providers.csv",
        provider_rows,
        [
            "provider_id",
            "runs_total",
            "feedback_total",
            "correct_total",
            "helped_total",
            "hurt_total",
            "neutral_total",
            "accuracy",
            "mean_run_latency_ms",
            "mean_provider_latency_ms",
            "mean_contribution_bp",
            "quality_mean_bp",
            "confidence_delta_bp",
        ],
    )
    _write_csv(
        out_dir / "sequences.csv",
        sequence_rows,
        ["sequence", "runs_total", "feedback_total", "correct_total", "accuracy", "mean_latency_ms"],
    )
    report = {
        "ok": True,
        "data_dir": str(root),
        "facts_dir": str(facts),
        "summary": {
            "runs_total": int(len(rows)),
            "feedback_total": int(feedback_coverage),
            "providers_total": int(len(provider_rows)),
            "sequences_total": int(len(sequence_rows)),
        },
        "recommendations": recs,
        "outputs": {
            "runs_csv": str(out_dir / "runs.csv"),
            "providers_csv": str(out_dir / "providers.csv"),
            "sequences_csv": str(out_dir / "sequences.csv"),
        },
        "provider_rows": provider_rows,
        "sequence_rows": sequence_rows,
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
