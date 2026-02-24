#!/usr/bin/env python3
"""Run blind popup-query acceptance checks against live corpus data.

This tool samples natural-language queries from case files and exercises the
Hypervisor popup contract endpoint:
  POST /api/query/popup

Acceptance policy (strict, no shortcuts):
- response.ok == true
- state == "ok"
- summary is non-empty and does not contain "indeterminate"
- citations list is non-empty
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    values = sorted(float(x) for x in samples)
    if len(values) == 1:
        return float(values[0])
    pct = min(100.0, max(0.0, float(p)))
    pos = (pct / 100.0) * float(len(values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - float(lo)
    return float(values[lo] * (1.0 - frac) + values[hi] * frac)


def _counter(rows: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in rows:
        label = str(key or "").strip()
        if not label:
            continue
        out[label] = int(out.get(label, 0) + 1)
    return out


def _top_counter_key(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    items = sorted(((int(v), str(k)) for k, v in counts.items()), key=lambda item: (-item[0], item[1]))
    return str(items[0][1]) if items else ""


def _read_cases(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    if isinstance(payload, dict):
        items = payload.get("cases", [])
    else:
        items = payload
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("question") or item.get("query") or "").strip()
        if not query:
            continue
        rows.append(
            {
                "id": str(item.get("id") or "").strip(),
                "query": query,
                "source": str(path),
            }
        )
    return rows


def _http_json(*, url: str, timeout_s: float, method: str = "GET", headers: dict[str, str] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else None
    req = Request(str(url), data=body, method=str(method).upper())
    if isinstance(headers, dict):
        for k, v in headers.items():
            req.add_header(str(k), str(v))
    if body is not None and "Content-Type" not in {str(k) for k in (headers or {}).keys()}:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=float(timeout_s)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "status": int(getattr(resp, "status", 200) or 200), "json": parsed}
    except HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return {
            "ok": False,
            "status": int(exc.code),
            "error": f"http_error:{exc.code}",
            "json": json.loads(raw) if raw.strip().startswith("{") else {},
            "raw": raw,
        }
    except URLError as exc:
        return {"ok": False, "status": 0, "error": f"url_error:{exc.reason}", "json": {}}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"request_failed:{type(exc).__name__}:{exc}", "json": {}}


def _fetch_popup_token(base_url: str, timeout_s: float) -> str:
    out = _http_json(url=f"{base_url.rstrip('/')}/api/auth/token", timeout_s=timeout_s, method="GET")
    payload = out.get("json", {}) if isinstance(out.get("json", {}), dict) else {}
    return str(payload.get("token") or "").strip()


@dataclass(frozen=True)
class AcceptanceDecision:
    accepted: bool
    reasons: list[str]


def _is_transport_failure(*, http_ok: bool, http_status: int, http_error: str, payload: dict[str, Any]) -> bool:
    if not bool(http_ok):
        return True
    if int(http_status) <= 0:
        return True
    if int(http_status) >= 500:
        return True
    if str(http_error or "").strip():
        return True
    error_text = str(payload.get("error") or "").strip().casefold()
    if error_text and ("timeout" in error_text or "upstream" in error_text):
        return True
    state = str(payload.get("state") or "").strip().casefold()
    blocked = str(payload.get("processing_blocked_reason") or "").strip()
    if state in {"degraded", "error"} and blocked:
        return True
    return False


def _failure_class(
    *,
    accepted: bool,
    http_ok: bool,
    http_status: int,
    http_error: str,
    payload: dict[str, Any],
) -> str:
    if bool(accepted):
        return "none"
    if _is_transport_failure(
        http_ok=bool(http_ok),
        http_status=int(http_status),
        http_error=str(http_error or ""),
        payload=payload,
    ):
        return "transport"
    return "answer_quality"


def _evaluate_popup_payload(payload: dict[str, Any]) -> AcceptanceDecision:
    reasons: list[str] = []
    if not bool(payload.get("ok", False)):
        reasons.append("popup_ok_false")
    state = str(payload.get("state") or "").strip().casefold()
    if state != "ok":
        reasons.append("state_not_ok")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        reasons.append("summary_empty")
    elif "indeterminate" in summary.casefold():
        reasons.append("summary_indeterminate")
    citations = payload.get("citations", [])
    if not isinstance(citations, list) or len(citations) == 0:
        reasons.append("citations_missing")
    return AcceptanceDecision(accepted=(len(reasons) == 0), reasons=reasons)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blind popup-query acceptance over sampled query corpus.")
    parser.add_argument(
        "--cases",
        nargs="+",
        default=[
            "docs/query_eval_cases_advanced20.json",
            "docs/query_eval_cases_generic20.json",
        ],
    )
    parser.add_argument("--sample-size", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260224)
    parser.add_argument("--all-cases", action="store_true", help="Ignore sample-size and run all available cases.")
    parser.add_argument("--base-url", default=os.environ.get("AUTOCAPTURE_WEB_BASE_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--timeout-s", type=float, default=45.0)
    parser.add_argument("--max-citations", type=int, default=6)
    parser.add_argument("--out", default="")
    parser.add_argument("--misses-out", default="")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any sampled query fails acceptance.")
    args = parser.parse_args(argv)

    pools: list[dict[str, str]] = []
    for raw in args.cases:
        path = Path(str(raw))
        if not path.exists():
            print(json.dumps({"ok": False, "error": "cases_not_found", "path": str(path)}))
            return 2
        pools.extend(_read_cases(path))
    if not pools:
        print(json.dumps({"ok": False, "error": "no_queries_loaded"}))
        return 2

    rng = random.Random(int(args.seed))
    rows = pools if bool(args.all_cases) else rng.sample(pools, k=min(int(args.sample_size), len(pools)))

    token = _fetch_popup_token(str(args.base_url), float(args.timeout_s))
    if not token:
        print(json.dumps({"ok": False, "error": "popup_token_missing", "base_url": str(args.base_url)}))
        return 2

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        query = str(row.get("query") or "")
        started = time.perf_counter()
        resp = _http_json(
            url=f"{str(args.base_url).rstrip('/')}/api/query/popup",
            timeout_s=float(args.timeout_s),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            payload={"query": query, "max_citations": int(args.max_citations)},
        )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        payload = resp.get("json", {}) if isinstance(resp.get("json", {}), dict) else {}
        decision = _evaluate_popup_payload(payload)
        http_ok = bool(resp.get("ok", False))
        http_status = int(resp.get("status", 0) or 0)
        http_error = str(resp.get("error") or "")
        failure_class = _failure_class(
            accepted=bool(decision.accepted),
            http_ok=http_ok,
            http_status=http_status,
            http_error=http_error,
            payload=payload,
        )
        failure_key = "accepted"
        if failure_class == "transport":
            failure_key = http_error or str(payload.get("processing_blocked_reason") or "") or str(payload.get("error") or "") or "transport_failure"
        elif failure_class == "answer_quality":
            failure_key = str((decision.reasons[0] if decision.reasons else "answer_quality_failure"))
        out_rows.append(
            {
                "id": str(row.get("id") or ""),
                "query": query,
                "source": str(row.get("source") or ""),
                "accepted": bool(decision.accepted),
                "failure_class": failure_class,
                "failure_key": str(failure_key),
                "failure_reasons": list(decision.reasons),
                "http_ok": http_ok,
                "http_status": http_status,
                "http_error": http_error,
                "state": str(payload.get("state") or ""),
                "summary": str(payload.get("summary") or ""),
                "citations_count": len(payload.get("citations", [])) if isinstance(payload.get("citations", []), list) else 0,
                "query_run_id": str(payload.get("query_run_id") or ""),
                "latency_ms": latency_ms,
                "response": payload,
            }
        )

    accepted_count = sum(1 for row in out_rows if bool(row.get("accepted", False)))
    failed_rows = [row for row in out_rows if not bool(row.get("accepted", False))]
    latencies = [float(row.get("latency_ms", 0.0) or 0.0) for row in out_rows]
    failure_class_counts = {
        "transport": sum(1 for row in failed_rows if str(row.get("failure_class") or "") == "transport"),
        "answer_quality": sum(1 for row in failed_rows if str(row.get("failure_class") or "") == "answer_quality"),
    }
    failure_key_counts = _counter([str(row.get("failure_key") or "") for row in failed_rows])
    failure_reason_counts = _counter([str(reason) for row in failed_rows for reason in list(row.get("failure_reasons") or [])])
    p50_ms = round(_percentile(latencies, 50.0), 3)
    p95_ms = round(_percentile(latencies, 95.0), 3)
    top_failure_class = _top_counter_key(failure_class_counts)
    top_failure_key = _top_counter_key(failure_key_counts)

    output_path = Path(str(args.out).strip()) if str(args.out).strip() else Path("artifacts/query_acceptance") / f"blind_popup_{_utc_stamp()}.json"
    report = {
        "ok": True,
        "mode": "blind_popup_acceptance",
        "ts_utc": _utc_iso(),
        "base_url": str(args.base_url),
        "seed": int(args.seed),
        "sample_count": len(out_rows),
        "accepted_count": int(accepted_count),
        "failed_count": int(len(failed_rows)),
        "transport_failures_count": int(failure_class_counts["transport"]),
        "answer_quality_failures_count": int(failure_class_counts["answer_quality"]),
        "failure_class_counts": failure_class_counts,
        "failure_key_counts": failure_key_counts,
        "failure_reason_counts": failure_reason_counts,
        "latency_p50_ms": float(p50_ms),
        "latency_p95_ms": float(p95_ms),
        "top_failure_class": str(top_failure_class),
        "top_failure_key": str(top_failure_key),
        "rows": out_rows,
    }
    _write_json(output_path, report)

    misses_out = Path(str(args.misses_out).strip()) if str(args.misses_out).strip() else Path("artifacts/query_acceptance") / "popup_regression_misses_latest.json"
    misses_payload = {
        "schema_version": 1,
        "record_type": "derived.eval.popup_regression_misses",
        "generated_at_utc": _utc_iso(),
        "source_report": str(output_path),
        "cases": [
            {
                "id": f"POP_MISS_{idx:02d}",
                "query": str(row.get("query") or ""),
                "source_case_id": str(row.get("id") or ""),
                "source_file": str(row.get("source") or ""),
                "expected": {
                    "popup_ok": True,
                    "state": "ok",
                    "citations_min": 1,
                    "summary_disallow_tokens": ["indeterminate"],
                },
                "observed": {
                    "state": str(row.get("state") or ""),
                    "citations_count": int(row.get("citations_count", 0) or 0),
                    "summary": str(row.get("summary") or ""),
                    "failure_class": str(row.get("failure_class") or ""),
                    "failure_key": str(row.get("failure_key") or ""),
                    "failure_reasons": list(row.get("failure_reasons") or []),
                },
            }
            for idx, row in enumerate(failed_rows, start=1)
        ],
    }
    _write_json(misses_out, misses_payload)

    summary = {
        "ok": True,
        "report": str(output_path),
        "misses": str(misses_out),
        "sample_count": len(out_rows),
        "accepted_count": accepted_count,
        "failed_count": len(failed_rows),
        "latency_p50_ms": float(p50_ms),
        "latency_p95_ms": float(p95_ms),
        "top_failure_class": str(top_failure_class),
        "top_failure_key": str(top_failure_key),
    }
    print(json.dumps(summary, sort_keys=True))
    if bool(args.strict) and failed_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
