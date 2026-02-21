#!/usr/bin/env python3
"""Gate: PromptOps latency regression checks (p50/p95)."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from autocapture.promptops.engine import PromptOpsLayer


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
    w = pos - lo
    return float(round(data[lo] * (1.0 - w) + data[hi] * w, 3))


def _regression_ok(
    *,
    observed_ms: float,
    baseline_ms: float,
    max_regression_pct: float,
    jitter_ms: float = 0.0,
) -> bool:
    if baseline_ms <= 0:
        return True
    allowed = baseline_ms * (1.0 + max(0.0, float(max_regression_pct))) + max(0.0, float(jitter_ms))
    return float(observed_ms) <= float(allowed)


def _config(tmp: str) -> dict[str, Any]:
    return {
        "paths": {"data_dir": tmp},
        "storage": {"data_dir": tmp},
        "plugins": {"safe_mode": True, "allowlist": [], "enabled": {}, "default_pack": [], "search_paths": []},
        "promptops": {
            "enabled": True,
            "mode": "auto_apply",
            "bundle_name": "missing",
            "sources": [],
            "strategy": "none",
            "query_strategy": "normalize_query",
            "require_citations": True,
            "history": {"enabled": False, "include_prompt": False},
            "github": {"enabled": False},
            "metrics": {"enabled": False},
            "review": {"enabled": False},
            "persist_prompts": False,
            "persist_query_prompts": False,
            "max_chars": 8000,
            "max_tokens": 2000,
            "banned_patterns": [],
        },
    }


def _measure(samples: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        layer = PromptOpsLayer(_config(tmp))
        query_lat_ms: list[float] = []
        model_lat_ms: list[float] = []
        for idx in range(int(max(1, samples))):
            q = f"pls help w/ query {idx}"
            t0 = time.perf_counter()
            _ = layer.prepare_query(q, prompt_id="query")
            query_lat_ms.append((time.perf_counter() - t0) * 1000.0)
            t1 = time.perf_counter()
            _ = layer.prepare_prompt(
                f"Summarize this query {idx}",
                prompt_id="llm.local",
                strategy="model_contract",
                persist=False,
            )
            model_lat_ms.append((time.perf_counter() - t1) * 1000.0)
    return {
        "query_p50_ms": _pct(query_lat_ms, 50.0),
        "query_p95_ms": _pct(query_lat_ms, 95.0),
        "query_p99_ms": _pct(query_lat_ms, 99.0),
        "model_p50_ms": _pct(model_lat_ms, 50.0),
        "model_p95_ms": _pct(model_lat_ms, 95.0),
        "model_p99_ms": _pct(model_lat_ms, 99.0),
        "samples": int(max(1, samples)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument("--max-query-p95-ms", type=float, default=250.0)
    parser.add_argument("--max-model-p95-ms", type=float, default=350.0)
    parser.add_argument("--max-regression-pct", type=float, default=0.35)
    parser.add_argument(
        "--regression-jitter-ms",
        type=float,
        default=30.0,
        help="Fixed additive jitter allowance for baseline regression checks.",
    )
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--baseline", default="artifacts/perf/promptops_perf_baseline.json")
    parser.add_argument("--output", default="artifacts/perf/gate_promptops_perf.json")
    args = parser.parse_args(argv)

    metrics = _measure(int(args.samples))
    baseline_path = Path(str(args.baseline))
    output_path = Path(str(args.output))
    baseline: dict[str, Any] = {}
    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception:
            baseline = {}

    checks = [
        {
            "name": "query_p95_absolute",
            "ok": float(metrics["query_p95_ms"]) <= float(args.max_query_p95_ms),
            "observed_ms": float(metrics["query_p95_ms"]),
            "max_ms": float(args.max_query_p95_ms),
        },
        {
            "name": "model_p95_absolute",
            "ok": float(metrics["model_p95_ms"]) <= float(args.max_model_p95_ms),
            "observed_ms": float(metrics["model_p95_ms"]),
            "max_ms": float(args.max_model_p95_ms),
        },
    ]
    if baseline:
        checks.extend(
            [
                {
                    "name": "query_p95_regression",
                    "ok": _regression_ok(
                        observed_ms=float(metrics["query_p95_ms"]),
                        baseline_ms=float(baseline.get("query_p95_ms", 0.0) or 0.0),
                        max_regression_pct=float(args.max_regression_pct),
                        jitter_ms=float(args.regression_jitter_ms),
                    ),
                    "observed_ms": float(metrics["query_p95_ms"]),
                    "baseline_ms": float(baseline.get("query_p95_ms", 0.0) or 0.0),
                    "max_regression_pct": float(args.max_regression_pct),
                    "jitter_ms": float(args.regression_jitter_ms),
                },
                {
                    "name": "model_p95_regression",
                    "ok": _regression_ok(
                        observed_ms=float(metrics["model_p95_ms"]),
                        baseline_ms=float(baseline.get("model_p95_ms", 0.0) or 0.0),
                        max_regression_pct=float(args.max_regression_pct),
                        jitter_ms=float(args.regression_jitter_ms),
                    ),
                    "observed_ms": float(metrics["model_p95_ms"]),
                    "baseline_ms": float(baseline.get("model_p95_ms", 0.0) or 0.0),
                    "max_regression_pct": float(args.max_regression_pct),
                    "jitter_ms": float(args.regression_jitter_ms),
                },
            ]
        )

    if args.update_baseline or not baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")

    payload = {
        "schema_version": 1,
        "ok": all(bool(c.get("ok")) for c in checks),
        "metrics": metrics,
        "baseline": baseline,
        "checks": checks,
        "baseline_path": str(baseline_path),
        "samples": int(metrics.get("samples", 0)),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if payload["ok"]:
        print("OK: promptops perf gate")
        return 0
    print("FAIL: promptops perf gate")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
