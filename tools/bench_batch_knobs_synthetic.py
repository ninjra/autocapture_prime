#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from autocapture_nx.runtime.batch import _apply_adaptive_idle_parallelism, _estimate_sla_snapshot


def _base_config(workers: int) -> dict[str, Any]:
    workers = max(1, int(workers))
    return {
        "runtime": {"budgets": {"cpu_max_utilization": 0.5, "ram_max_utilization": 0.5}},
        "storage": {"retention": {"evidence": "6d"}},
        "processing": {
            "idle": {
                "max_concurrency_cpu": workers,
                "batch_size": workers * 3,
                "max_items_per_run": workers * 20,
                "adaptive_parallelism": {
                    "enabled": True,
                    "cpu_min": 1,
                    "cpu_max": max(workers, 8),
                    "cpu_step_up": 1,
                    "cpu_step_down": 1,
                    "batch_per_worker": 3,
                    "items_per_worker": 20,
                    "low_watermark": 0.65,
                    "high_watermark": 0.9,
                },
                "sla_control": {
                    "enabled": True,
                    "retention_horizon_hours": 144.0,
                    "lag_warn_ratio": 0.8,
                    "cpu_step_up_on_risk": 1,
                },
            }
        },
    }


def _synthetic_steps(*, workers: int, pending: int, completed_per_step: int, loops: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    remaining = max(0, int(pending))
    for idx in range(max(1, int(loops))):
        completed = min(remaining, max(0, int(completed_per_step)) * max(1, int(workers)))
        remaining = max(0, remaining - completed)
        rows.append(
            {
                "loop": int(idx),
                "consumed_ms": 1000,
                "idle_stats": {
                    "pending_records": int(remaining),
                    "records_completed": int(completed),
                },
            }
        )
    return rows


def _bench_eval_runtime(config: dict[str, Any], *, steps: list[dict[str, Any]], repeats: int) -> tuple[float, dict[str, Any]]:
    durations_us: list[float] = []
    snapshot: dict[str, Any] = {}
    for _ in range(max(1, int(repeats))):
        started = time.perf_counter()
        snapshot = _estimate_sla_snapshot(config, steps=steps)
        elapsed_us = (time.perf_counter() - started) * 1_000_000.0
        durations_us.append(float(elapsed_us))
    median_us = statistics.median(durations_us) if durations_us else 0.0
    return float(median_us), snapshot


def run_bench(*, workers: list[int], pending: int, completed_per_step: int, loops: int, repeats: int) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for worker_count in [max(1, int(w)) for w in workers]:
        cfg = _base_config(worker_count)
        low_signal = _apply_adaptive_idle_parallelism(cfg, signals={"cpu_utilization": 0.05, "ram_utilization": 0.05})
        high_signal = _apply_adaptive_idle_parallelism(cfg, signals={"cpu_utilization": 0.49, "ram_utilization": 0.49})
        steps = _synthetic_steps(
            workers=worker_count,
            pending=int(pending),
            completed_per_step=int(completed_per_step),
            loops=int(loops),
        )
        median_us, snapshot = _bench_eval_runtime(cfg, steps=steps, repeats=int(repeats))
        scenarios.append(
            {
                "workers": int(worker_count),
                "adaptive_low_signal": low_signal,
                "adaptive_high_signal": high_signal,
                "sla": snapshot,
                "eval_median_us": float(round(median_us, 3)),
            }
        )
    return {"ok": True, "schema_version": 1, "scenarios": scenarios}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthetic microbench for batch knobs and SLA math.")
    parser.add_argument("--workers", default="1,2,4,8", help="Comma-separated worker counts.")
    parser.add_argument("--pending", type=int, default=10000, help="Initial pending records.")
    parser.add_argument("--completed-per-step", type=int, default=50, help="Completed records per step per worker.")
    parser.add_argument("--loops", type=int, default=30, help="Synthetic loop count.")
    parser.add_argument("--repeats", type=int, default=50, help="Timing repeats per scenario.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    workers = [int(part.strip()) for part in str(args.workers).split(",") if part.strip()]
    payload = run_bench(
        workers=workers,
        pending=int(args.pending),
        completed_per_step=int(args.completed_per_step),
        loops=int(args.loops),
        repeats=int(args.repeats),
    )
    out = str(args.output or "").strip()
    if out:
        out_path = Path(out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
