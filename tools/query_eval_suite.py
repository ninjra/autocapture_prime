#!/usr/bin/env python3
"""Run golden query checks and emit append-only evaluation metrics.

Case schema:
[
  {
    "id": "song",
    "query": "what song is playing",
    "expects_any": ["sunlight", "jennifer doherty"],
    "expects_all": []
  }
]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.query import run_query
from autocapture_nx.storage.facts_ndjson import append_fact_line


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return [item for item in payload["cases"] if isinstance(item, dict)]
    raise ValueError("cases file must be a list or {'cases': [...]}")


def _answer_text(result: dict[str, Any]) -> str:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
    texts = []
    for claim in claims:
        if isinstance(claim, dict):
            txt = str(claim.get("text") or "").strip()
            if txt:
                texts.append(txt)
    return "\n".join(texts)


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    query: str
    passed: bool
    answer_text: str
    detail: str
    result: dict[str, Any]


def _run_case(system, case: dict[str, Any]) -> CaseOutcome:  # type: ignore[no-untyped-def]
    case_id = str(case.get("id") or sha256_text(json.dumps(case, sort_keys=True))[:12])
    query = str(case.get("query") or "").strip()
    if not query:
        return CaseOutcome(case_id, query, False, "", "missing_query", {})
    expects_any = [str(x).strip().lower() for x in (case.get("expects_any") or []) if str(x).strip()]
    expects_all = [str(x).strip().lower() for x in (case.get("expects_all") or []) if str(x).strip()]
    try:
        result = run_query(system, query, schedule_extract=False)
    except Exception as exc:
        return CaseOutcome(case_id, query, False, "", f"query_failed:{type(exc).__name__}:{exc}", {})
    text = _answer_text(result)
    low = text.lower()
    any_ok = True if not expects_any else any(token in low for token in expects_any)
    all_ok = all(token in low for token in expects_all)
    passed = bool(any_ok and all_ok)
    detail = "ok" if passed else f"expectation_failed:any_ok={any_ok},all_ok={all_ok}"
    return CaseOutcome(case_id, query, passed, text, detail, result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, help="Path to cases JSON.")
    parser.add_argument("--safe-mode", action="store_true")
    args = parser.parse_args(argv)

    cases = _load_cases(Path(args.cases))
    kernel = Kernel(default_config_paths(), safe_mode=bool(args.safe_mode))
    system = kernel.boot(start_conductor=False, fast_boot=False)
    config = getattr(system, "config", {})
    rows: list[dict[str, Any]] = []
    passed = 0
    total = 0
    try:
        for case in cases:
            out = _run_case(system, case)
            total += 1
            if out.passed:
                passed += 1
            result = out.result if isinstance(out.result, dict) else {}
            answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
            eval_obj = result.get("evaluation", {}) if isinstance(result.get("evaluation", {}), dict) else {}
            row = {
                "schema_version": 1,
                "record_type": "derived.eval.golden_case",
                "ts_utc": _utc(),
                "case_id": out.case_id,
                "query": out.query,
                "query_sha256": sha256_text(out.query),
                "passed": bool(out.passed),
                "detail": out.detail,
                "answer_state": str(answer.get("state") or ""),
                "answer_claim_count": int(len(answer.get("claims", []))) if isinstance(answer.get("claims", []), list) else 0,
                "coverage_bp": int(round(float(eval_obj.get("coverage_ratio", 0.0) or 0.0) * 10000.0)),
                "custom_claims_count": int(((result.get("custom_claims", {}) or {}).get("count") or 0)),
                "synth_claims_count": int(((result.get("synth_claims", {}) or {}).get("count") or 0)),
                "synth_backend": str((((result.get("synth_claims", {}) or {}).get("debug", {}) or {}).get("backend") or "")),
                "synth_model": str((((result.get("synth_claims", {}) or {}).get("debug", {}) or {}).get("model") or "")),
                "answer_text": out.answer_text,
            }
            rows.append(row)
            try:
                _ = append_fact_line(config, rel_path="query_eval_suite.ndjson", payload=row)
            except Exception:
                pass
    finally:
        kernel.shutdown()

    summary = {
        "ok": passed == total and total > 0,
        "cases_total": total,
        "cases_passed": passed,
        "cases_failed": max(0, total - passed),
        "rows": rows,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
