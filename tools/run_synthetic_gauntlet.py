#!/usr/bin/env python3
"""Run synthetic query gauntlets (40+40 style) with latency/citation metrics."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.query import run_query

DEFAULT_CASE_PATHS = [
    "docs/query_eval_cases_generic20.json",
    "docs/query_eval_cases_advanced20.json",
    "docs/query_eval_cases_stage2_time40.json",
    "docs/query_eval_cases_temporal_screenshot_qa_40.json",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return [row for row in payload.get("cases", []) if isinstance(row, dict)]
    return []


def _claim_texts(result: dict[str, Any]) -> list[str]:
    answer = result.get("answer", {}) if isinstance(result.get("answer"), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display"), dict) else {}
    texts: list[str] = []
    summary = str(display.get("summary") or "").strip()
    if summary:
        texts.append(summary)
    bullets = display.get("bullets", []) if isinstance(display.get("bullets"), list) else []
    for item in bullets:
        line = str(item or "").strip()
        if line:
            texts.append(line)
    claims = answer.get("claims", []) if isinstance(answer.get("claims"), list) else []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _citation_count(result: dict[str, Any]) -> int:
    answer = result.get("answer", {}) if isinstance(result.get("answer"), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims"), list) else []
    total = 0
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        cites = claim.get("citations", [])
        if isinstance(cites, list):
            total += int(len(cites))
    return int(total)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0.0, min(1.0, float(q))) * float(len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - float(low)
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def _evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> tuple[bool, bool, str]:
    texts = _claim_texts(result)
    joined = "\n".join(texts).lower()
    expects_any = [str(x).strip().lower() for x in (case.get("expects_any") or []) if str(x).strip()]
    expects_all = [str(x).strip().lower() for x in (case.get("expects_all") or []) if str(x).strip()]
    raw_exact = case.get("expect_exact")
    if raw_exact is None:
        raw_exact = case.get("expects_exact")
    if isinstance(raw_exact, list):
        expects_exact = [str(x).strip() for x in raw_exact if str(x).strip()]
    elif raw_exact is None:
        expects_exact = []
    else:
        expects_exact = [str(raw_exact).strip()] if str(raw_exact).strip() else []

    strict_case = bool(expects_any or expects_all or expects_exact)
    require_citations = bool(case.get("require_citations", strict_case))

    any_ok = True if not expects_any else any(token in joined for token in expects_any)
    all_ok = all(token in joined for token in expects_all)
    exact_ok = True
    if expects_exact:
        norm_claims = [" ".join(text.casefold().split()) for text in texts]
        norm_expected = [" ".join(text.casefold().split()) for text in expects_exact]
        exact_ok = any(exp in claim for exp in norm_expected for claim in norm_claims)

    cite_count = _citation_count(result)
    citations_ok = (not require_citations) or cite_count > 0
    passed = bool(any_ok and all_ok and exact_ok and citations_ok)
    detail = (
        "ok"
        if passed
        else f"expectation_failed:any_ok={any_ok},all_ok={all_ok},exact_ok={exact_ok},citations_ok={citations_ok}"
    )
    return strict_case, passed, detail


def _run_bundle(
    system: Any,
    *,
    bundle_name: str,
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    strict_total = 0
    strict_passed = 0
    citation_hit = 0
    for idx, case in enumerate(cases):
        query = str(case.get("query") or case.get("question") or "").strip()
        case_id = str(case.get("id") or f"{bundle_name}_{idx+1}")
        if not query:
            rows.append(
                {
                    "bundle": bundle_name,
                    "id": case_id,
                    "query": query,
                    "ok": False,
                    "strict": False,
                    "detail": "missing_query",
                    "latency_ms": 0.0,
                    "citation_count": 0,
                }
            )
            continue
        started = time.perf_counter()
        try:
            result = run_query(system, query, schedule_extract=False)
            call_error = ""
        except Exception as exc:
            result = {}
            call_error = f"{type(exc).__name__}:{exc}"
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        latencies.append(latency_ms)
        strict_case = False
        passed = False
        detail = ""
        if call_error:
            detail = f"query_failed:{call_error}"
        else:
            strict_case, passed, detail = _evaluate_case(case, result)
        if strict_case:
            strict_total += 1
            if passed:
                strict_passed += 1
        cites = _citation_count(result)
        if cites > 0:
            citation_hit += 1
        answer = result.get("answer", {}) if isinstance(result.get("answer"), dict) else {}
        rows.append(
            {
                "bundle": bundle_name,
                "id": case_id,
                "query": query,
                "query_sha256": sha256_text(query),
                "ok": bool((not strict_case and not call_error) or (strict_case and passed)),
                "strict": bool(strict_case),
                "detail": detail if detail else "ok",
                "latency_ms": float(round(latency_ms, 3)),
                "citation_count": int(cites),
                "answer_state": str(answer.get("state") or ""),
            }
        )
    bundle_summary = {
        "bundle": bundle_name,
        "cases_total": int(len(rows)),
        "strict_total": int(strict_total),
        "strict_passed": int(strict_passed),
        "strict_failed": int(max(0, strict_total - strict_passed)),
        "citations_present_cases": int(citation_hit),
        "latency_ms_p50": float(round(_percentile(latencies, 0.50), 3)),
        "latency_ms_p95": float(round(_percentile(latencies, 0.95), 3)),
        "latency_ms_mean": float(round(statistics.fmean(latencies), 3)) if latencies else 0.0,
    }
    return rows, bundle_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic query gauntlet bundles and emit metrics.")
    parser.add_argument(
        "--cases",
        action="append",
        default=[],
        help="Case file path. May repeat. Defaults: generic20 + advanced20 + stage2_time40.",
    )
    parser.add_argument("--output", default="artifacts/query_gauntlet/synthetic_gauntlet_latest.json")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--safe-mode", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--metadata-only", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)

    case_paths = [str(x) for x in args.cases if str(x).strip()]
    if not case_paths:
        case_paths = list(DEFAULT_CASE_PATHS)

    prev_metadata_only = os.environ.get("AUTOCAPTURE_QUERY_METADATA_ONLY")
    if bool(args.metadata_only):
        os.environ["AUTOCAPTURE_QUERY_METADATA_ONLY"] = "1"
    kernel: Kernel | None = None
    system: Any | None = None
    boot_mode = ""
    boot_attempts: list[str] = []
    last_exc: Exception | None = None
    for safe_mode, fast_boot in (
        (bool(args.safe_mode), False),
        (bool(args.safe_mode), True),
        (False, False),
        (False, True),
    ):
        boot_attempts.append(f"safe_mode={safe_mode},fast_boot={fast_boot}")
        current = Kernel(default_config_paths(), safe_mode=bool(safe_mode))
        try:
            system = current.boot(start_conductor=False, fast_boot=bool(fast_boot))
            has_metadata = bool(getattr(system, "has", lambda _name: False)("storage.metadata"))
            if has_metadata:
                kernel = current
                boot_mode = boot_attempts[-1]
                break
            last_exc = RuntimeError("missing_capability:storage.metadata")
            try:
                current.shutdown()
            except Exception:
                pass
            continue
        except Exception as exc:
            last_exc = exc
            try:
                current.shutdown()
            except Exception:
                pass
    if kernel is None or system is None:
        detail = f"{type(last_exc).__name__}:{last_exc}" if last_exc is not None else "unknown_boot_failure"
        payload = {
            "ok": False,
            "schema_version": 1,
            "ts_utc": _utc_now(),
            "error": f"kernel_boot_failed:{detail}",
            "boot_attempts": boot_attempts,
        }
        out_path = Path(str(args.output)).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["output"] = str(out_path)
        print(json.dumps(payload, sort_keys=True))
        return 1
    all_rows: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    try:
        for raw in case_paths:
            path = Path(str(raw)).expanduser()
            cases = _load_cases(path)
            rows, bundle_summary = _run_bundle(system, bundle_name=str(path), cases=cases)
            all_rows.extend(rows)
            bundles.append(bundle_summary)
    finally:
        kernel.shutdown()
        if bool(args.metadata_only):
            if prev_metadata_only is None:
                os.environ.pop("AUTOCAPTURE_QUERY_METADATA_ONLY", None)
            else:
                os.environ["AUTOCAPTURE_QUERY_METADATA_ONLY"] = prev_metadata_only

    strict_total = int(sum(int(row.get("strict_total", 0) or 0) for row in bundles))
    strict_passed = int(sum(int(row.get("strict_passed", 0) or 0) for row in bundles))
    strict_failed = int(max(0, strict_total - strict_passed))
    latencies = [float(row.get("latency_ms", 0.0) or 0.0) for row in all_rows if isinstance(row, dict)]
    citation_cases = sum(1 for row in all_rows if int(row.get("citation_count", 0) or 0) > 0)
    payload = {
        "ok": bool(strict_failed == 0 if bool(args.strict) else True),
        "schema_version": 1,
        "ts_utc": _utc_now(),
        "boot_mode": str(boot_mode),
        "metadata_only": bool(args.metadata_only),
        "safe_mode": bool(args.safe_mode),
        "strict_mode": bool(args.strict),
        "summary": {
            "evaluated": int(len(all_rows)),
            "strict_evaluated": int(strict_total),
            "strict_passed": int(strict_passed),
            "strict_failed": int(strict_failed),
            "non_strict_evaluated": int(max(0, len(all_rows) - strict_total)),
            "citation_present_cases": int(citation_cases),
            "latency_ms_p50": float(round(_percentile(latencies, 0.50), 3)),
            "latency_ms_p95": float(round(_percentile(latencies, 0.95), 3)),
            "latency_ms_mean": float(round(statistics.fmean(latencies), 3)) if latencies else 0.0,
        },
        "bundles": bundles,
        "rows": all_rows,
    }
    out_path = Path(str(args.output)).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
