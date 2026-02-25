#!/usr/bin/env python3
"""Evaluate real-corpus readiness from advanced/generic query artifacts.

Blocking semantics:
- strict cases are sourced from docs/contracts/real_corpus_expected_answers_v1.json
- strict matrix must satisfy evaluated=total, skipped=0, failed=0

Non-blocking semantics:
- generic suite is informational only and reported separately
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return [row for row in payload.get("cases", []) if isinstance(row, dict)]
    return []


def _latest_matching(pattern: str) -> Path | None:
    root = Path("artifacts/advanced10")
    if not root.exists():
        return None
    found = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def _resolve_report_path(explicit: str, pattern: str, latest_name: str) -> Path:
    if explicit.strip():
        return Path(explicit.strip())
    latest = Path("artifacts/advanced10") / latest_name
    if latest.exists():
        return latest
    fallback = _latest_matching(pattern)
    if fallback is None:
        return latest
    return fallback


def _provider_citation_count(row: dict[str, Any]) -> int:
    providers = row.get("providers", [])
    if not isinstance(providers, list):
        return 0
    total = 0
    for item in providers:
        if not isinstance(item, dict):
            continue
        try:
            total += int(item.get("citation_count", 0) or 0)
        except Exception:
            continue
    return int(total)


def _provider_diagnostics(row: dict[str, Any]) -> list[dict[str, Any]]:
    providers = row.get("providers", [])
    if not isinstance(providers, list):
        return []
    out: list[dict[str, Any]] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "provider_id": str(item.get("provider_id") or ""),
                "claim_count": int(item.get("claim_count", 0) or 0),
                "citation_count": int(item.get("citation_count", 0) or 0),
                "record_types": [str(x) for x in (item.get("record_types") or []) if str(x)],
                "doc_kinds": [str(x) for x in (item.get("doc_kinds") or []) if str(x)],
                "signal_keys_sample": [str(x) for x in (item.get("signal_keys") or [])[:6] if str(x)],
            }
        )
    return out


def _extract_citation_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    raw_citations = row.get("citations")
    if isinstance(raw_citations, list):
        for item in raw_citations:
            if isinstance(item, dict):
                entries.append(dict(item))
    answer = row.get("answer", {}) if isinstance(row.get("answer", {}), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        citations = claim.get("citations", []) if isinstance(claim.get("citations", []), list) else []
        for item in citations:
            if isinstance(item, dict):
                entries.append(dict(item))
    return entries


def _citation_linkage_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    citations = _extract_citation_entries(row)
    issues: list[str] = []
    parsed: list[dict[str, Any]] = []
    for item in citations:
        locator = item.get("locator", {}) if isinstance(item.get("locator", {}), dict) else {}
        evidence_id = str(item.get("evidence_id") or item.get("record_id") or locator.get("record_id") or "").strip()
        derived_id = str(item.get("derived_id") or "").strip()
        locator_kind = str(locator.get("kind") or "").strip()
        entry_issues: list[str] = []
        if not evidence_id:
            entry_issues.append("missing_evidence_id")
        if not locator_kind:
            entry_issues.append("missing_locator")
        if entry_issues:
            for issue in entry_issues:
                issues.append(issue)
        parsed.append(
            {
                "evidence_id": evidence_id,
                "derived_id": derived_id,
                "locator_kind": locator_kind,
                "issues": entry_issues,
            }
        )
    if not parsed:
        provider_rows = _provider_diagnostics(row)
        if provider_rows and _provider_citation_count(row) <= 0:
            issues.append("providers_claims_without_citations")
    return {
        "count": int(len(parsed)),
        "issues": sorted(set(str(x) for x in issues if str(x))),
        "entries": parsed[:10],
    }


def _row_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        out[cid] = row
    return out


def _strict_case_eval(case: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    case_id = str(case.get("id") or "").strip()
    reasons: list[str] = []
    skipped = False
    evaluated = False
    citations = 0
    answer_state = ""
    query_run_id = ""
    source_report = ""
    provider_diagnostics: list[dict[str, Any]] = []
    citation_linkage: dict[str, Any] = {"count": 0, "issues": [], "entries": []}
    if row is None:
        reasons.append("missing_row")
    else:
        query_run_id = str(row.get("query_run_id") or "").strip()
        source_report = str(row.get("source_report") or "").strip()
        provider_diagnostics = _provider_diagnostics(row)
        citation_linkage = _citation_linkage_diagnostics(row)
        skipped = bool(row.get("skipped", False))
        if skipped:
            reasons.append("row_skipped")
        else:
            evaluated = True
            if not bool(row.get("ok", False)):
                reasons.append("query_not_ok")
            ev = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
            if not bool(ev.get("evaluated", False)):
                reasons.append("expected_eval_not_evaluated")
            if not bool(ev.get("passed", False)):
                reasons.append("expected_eval_failed")
            answer_state = str(row.get("answer_state") or "").strip()
            allowed_states = case.get("allowed_answer_states", ["ok"])
            allowed = [str(x).strip() for x in allowed_states if str(x).strip()]
            if allowed and answer_state not in allowed:
                reasons.append("answer_state_disallowed")
            citations = _provider_citation_count(row)
            if bool(case.get("require_citations", True)) and citations <= 0:
                reasons.append("citations_missing")
            if not bool(case.get("allow_indeterminate", False)):
                summary = str(row.get("summary") or "")
                bullets = row.get("bullets", []) if isinstance(row.get("bullets", []), list) else []
                hay = " ".join([summary] + [str(x) for x in bullets]).strip().lower()
                if "indeterminate" in hay:
                    reasons.append("indeterminate_not_allowed")
    passed = len(reasons) == 0
    return {
        "id": case_id,
        "suite": str(case.get("suite") or ""),
        "passed": bool(passed),
        "evaluated": bool(evaluated),
        "skipped": bool(skipped),
        "reasons": reasons,
        "answer_state": answer_state,
        "citation_count": int(citations),
        "query_run_id": query_run_id,
        "source_report": source_report,
        "provider_diagnostics": provider_diagnostics,
        "citation_linkage": citation_linkage,
    }


def _coerce_query_contract_metrics(row: dict[str, Any]) -> tuple[dict[str, int], bool]:
    out = {
        "query_extractor_launch_total": 0,
        "query_schedule_extract_requests_total": 0,
        "query_raw_media_reads_total": 0,
    }
    metrics = row.get("query_contract_metrics", {}) if isinstance(row.get("query_contract_metrics", {}), dict) else {}
    has_top_level = all(
        key in row
        for key in (
            "query_extractor_launch_total",
            "query_schedule_extract_requests_total",
            "query_raw_media_reads_total",
        )
    )
    complete = bool(metrics) or has_top_level
    for key in out.keys():
        if key in metrics:
            out[key] = int(metrics.get(key, 0) or 0)
        elif key in row:
            out[key] = int(row.get(key, 0) or 0)
    return out, complete


def _row_latency_total_ms(row: dict[str, Any]) -> float | None:
    stage_ms = row.get("stage_ms", {}) if isinstance(row.get("stage_ms", {}), dict) else {}
    if "total" not in stage_ms:
        return None
    try:
        value = float(stage_ms.get("total", 0.0) or 0.0)
    except Exception:
        return None
    if value < 0.0:
        value = 0.0
    return float(value)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    rank = max(0.0, min(100.0, float(pct)))
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = (rank / 100.0) * (len(ordered) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _generic_eval(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    passed = 0
    skipped = 0
    failed_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if bool(row.get("skipped", False)):
            skipped += 1
            continue
        ev = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
        answer_state = str(row.get("answer_state") or "").strip()
        summary = str(row.get("summary") or "").strip()
        query_run_id = str(row.get("query_run_id") or "").strip()
        ok = bool(row.get("ok", False))
        ev_ok = bool(ev.get("passed", False))
        state_ok = answer_state in {"ok", "partial", "no_evidence"}
        row_ok = bool(ok and ev_ok and state_ok and bool(summary) and bool(query_run_id))
        if row_ok:
            passed += 1
        else:
            if cid:
                failed_ids.append(cid)
    total = len(rows)
    evaluated = max(0, total - skipped)
    failed = max(0, evaluated - passed)
    return {
        "total": int(total),
        "evaluated": int(evaluated),
        "passed": int(passed),
        "failed": int(failed),
        "skipped": int(skipped),
        "failed_ids": sorted(set(failed_ids)),
        "blocking": False,
    }


def _strict_eval(
    *,
    contract: dict[str, Any],
    advanced: dict[str, Any],
    generic: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    strict = contract.get("strict", {}) if isinstance(contract.get("strict", {}), dict) else {}
    cases = strict.get("cases", []) if isinstance(strict.get("cases", []), list) else []
    expected_total = int(strict.get("expected_total", len(cases)) or len(cases))
    adv_rows = _row_index(advanced)
    gen_rows = _row_index(generic)
    rows: list[dict[str, Any]] = []
    missing = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        suite = str(case.get("suite") or "").strip().lower()
        case_id = str(case.get("id") or "").strip()
        row = adv_rows.get(case_id) if suite.startswith("advanced") else gen_rows.get(case_id)
        out = _strict_case_eval(case, row)
        if isinstance(row, dict):
            qc_metrics, qc_complete = _coerce_query_contract_metrics(row)
            out["query_contract_metrics"] = qc_metrics
            out["query_contract_metrics_complete"] = bool(qc_complete)
            lat_ms = _row_latency_total_ms(row)
            if lat_ms is not None:
                out["query_latency_total_ms"] = float(lat_ms)
        rows.append(out)
        if "missing_row" in out.get("reasons", []):
            missing += 1
    strict_evaluated = sum(1 for row in rows if bool(row.get("evaluated", False)))
    strict_passed = sum(1 for row in rows if bool(row.get("passed", False)))
    strict_skipped = sum(1 for row in rows if bool(row.get("skipped", False)))
    strict_failed = max(0, len(rows) - strict_passed)
    failure_reasons: list[str] = []
    if expected_total != len(rows):
        failure_reasons.append("contract_expected_total_mismatch")
    if strict_evaluated != expected_total:
        failure_reasons.append("strict_matrix_evaluated_mismatch")
    if strict_skipped != 0:
        failure_reasons.append("strict_matrix_skipped_nonzero")
    if strict_failed != 0:
        failure_reasons.append("strict_matrix_failed_nonzero")
    if missing > 0:
        failure_reasons.append("strict_rows_missing")
    summary = {
        "matrix_total": int(expected_total),
        "matrix_evaluated": int(strict_evaluated),
        "matrix_passed": int(strict_passed),
        "matrix_failed": int(strict_failed),
        "matrix_skipped": int(strict_skipped),
        "missing_rows": int(missing),
    }
    return summary, rows, failure_reasons


def _classify_strict_failure_cause(row: dict[str, Any]) -> str:
    reasons = {str(x) for x in (row.get("reasons") or [])}
    answer_state = str(row.get("answer_state") or "").strip().lower()
    if "citations_missing" in reasons:
        return "citation_invalid"
    if answer_state in {"error", "degraded", "not_available_yet", "upstream_error"}:
        return "upstream_unreachable"
    if reasons.intersection({"missing_row", "row_skipped", "query_not_ok", "expected_eval_not_evaluated"}):
        return "upstream_unreachable"
    return "retrieval_miss"


def _strict_failure_cause_summary(strict_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "retrieval_miss": 0,
        "citation_invalid": 0,
        "upstream_unreachable": 0,
    }
    by_case: list[dict[str, Any]] = []
    for row in strict_rows:
        if not isinstance(row, dict):
            continue
        if bool(row.get("passed", False)):
            continue
        cid = str(row.get("id") or "").strip()
        cause = _classify_strict_failure_cause(row)
        counts[cause] = int(counts.get(cause, 0)) + 1
        by_case.append(
            {
                "id": cid,
                "cause": cause,
                "reasons": [str(x) for x in (row.get("reasons") or [])],
                "answer_state": str(row.get("answer_state") or ""),
                "citation_count": int(row.get("citation_count", 0) or 0),
                "query_run_id": str(row.get("query_run_id") or ""),
                "source_report": str(row.get("source_report") or ""),
                "provider_diagnostics": row.get("provider_diagnostics", []),
                "citation_linkage": row.get("citation_linkage", {}),
            }
        )
    return {"counts": counts, "by_case": by_case}


def _required_signals(case: dict[str, Any]) -> list[str]:
    out: list[str] = []
    paths = case.get("expected_paths", [])
    if isinstance(paths, list):
        for item in paths:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            equals = str(item.get("equals") or "").strip()
            if path and equals:
                out.append(f"path:{path}={equals}")
            elif path:
                out.append(f"path:{path}")
    tokens = case.get("expected_contains_all", [])
    if isinstance(tokens, list):
        for token in tokens[:3]:
            txt = str(token or "").strip()
            if txt:
                out.append(f"contains:{txt}")
    return out


def _source_path_disallowed(path_value: str, policy: dict[str, Any]) -> bool:
    if not str(path_value or "").strip():
        return False
    raw = str(path_value).strip().lower()
    disallowed = policy.get("disallowed_substrings", []) if isinstance(policy.get("disallowed_substrings", []), list) else []
    for token in disallowed:
        chk = str(token or "").strip().lower()
        if not chk:
            continue
        if chk in raw:
            return True
        # Also match with optional leading slash variations.
        if chk.startswith("/") and chk[1:] and chk[1:] in raw:
            return True
        if (not chk.startswith("/")) and ("/" + chk) in raw:
            return True
    return False


def _source_paths_valid(payload: dict[str, Any], policy: dict[str, Any]) -> bool:
    require_real = bool(policy.get("require_real_corpus", False))
    if not require_real:
        return True
    top_src = str(payload.get("source_report") or payload.get("report") or "").strip()
    if not top_src or _source_path_disallowed(top_src, policy):
        return False
    rows = payload.get("rows", []) if isinstance(payload.get("rows", []), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_src = str(row.get("source_report") or "").strip()
        if not row_src or _source_path_disallowed(row_src, policy):
            return False
    return True


def _normalize_source_tier(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"real", "synthetic", "mixed"}:
        return raw
    return "real"


def _resolve_report_path_with_policy(
    *,
    explicit: str,
    pattern: str,
    latest_name: str,
    source_policy: dict[str, Any],
) -> Path:
    # explicit always wins (caller asked for exact artifact).
    if str(explicit).strip():
        return Path(str(explicit).strip())
    root = Path("artifacts/advanced10")
    latest = root / latest_name
    candidates: list[Path] = []
    if latest.exists():
        candidates.append(latest)
    candidates.extend(sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True))
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    for path in ordered:
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if _source_paths_valid(payload, source_policy):
            return path
    # fallback to previous behavior for diagnostics (will fail later with explicit reason)
    return _resolve_report_path("", pattern, latest_name)


def _latest_lineage_report() -> Path | None:
    root = Path("artifacts/lineage")
    if not root.exists():
        return None
    found = sorted(
        root.glob("*/stage1_stage2_lineage_queryability.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return found[0] if found else None


def _coerce_nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    return max(0, int(out))


def _evaluate_queryability_slo(*, lineage_path: Path, min_ratio: float) -> dict[str, Any]:
    payload = _load_json(lineage_path)
    summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
    frames_total = _coerce_nonnegative_int(summary.get("frames_total"), default=0)
    frames_queryable = _coerce_nonnegative_int(summary.get("frames_queryable"), default=0)
    ratio = float(frames_queryable) / float(frames_total) if frames_total > 0 else 0.0
    return {
        "enabled": True,
        "lineage_report": str(lineage_path.resolve()),
        "frames_total": int(frames_total),
        "frames_queryable": int(frames_queryable),
        "queryable_ratio": float(ratio),
        "required_min_ratio": float(max(0.0, min(float(min_ratio), 1.0))),
    }


def _write_coverage_markdown(
    *,
    path: Path,
    strict_rows: list[dict[str, Any]],
    strict_cases: list[dict[str, Any]],
) -> None:
    case_map: dict[str, dict[str, Any]] = {}
    for case in strict_cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "").strip()
        if cid:
            case_map[cid] = case
    lines: list[str] = []
    lines.append("# Queryability Coverage Matrix")
    lines.append("")
    lines.append("| id | pass | evaluated | required_signals | reasons |")
    lines.append("|---|---:|---:|---|---|")
    for row in strict_rows:
        cid = str(row.get("id") or "").strip()
        case = case_map.get(cid, {})
        required = ", ".join(_required_signals(case))
        reasons = ", ".join([str(x) for x in (row.get("reasons") or [])])
        lines.append(
            "| {id} | {passed} | {evaluated} | {required} | {reasons} |".format(
                id=cid,
                passed="Y" if bool(row.get("passed", False)) else "N",
                evaluated="Y" if bool(row.get("evaluated", False)) else "N",
                required=required or "-",
                reasons=reasons or "-",
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_summary_markdown(
    *,
    path: Path,
    payload: dict[str, Any],
    metrics_path: Path,
    query_results_path: Path,
    coverage_md_path: Path,
) -> None:
    lines: list[str] = []
    lines.append("# Real-Corpus Strict Status")
    lines.append("")
    lines.append(f"- ok: `{bool(payload.get('ok', False))}`")
    lines.append(f"- matrix_total: `{int(payload.get('matrix_total', 0) or 0)}`")
    lines.append(f"- matrix_evaluated: `{int(payload.get('matrix_evaluated', 0) or 0)}`")
    lines.append(f"- matrix_passed: `{int(payload.get('matrix_passed', 0) or 0)}`")
    lines.append(f"- matrix_failed: `{int(payload.get('matrix_failed', 0) or 0)}`")
    lines.append(f"- matrix_skipped: `{int(payload.get('matrix_skipped', 0) or 0)}`")
    lines.append(f"- source_tier: `{str(payload.get('source_tier') or '')}`")
    lines.append(f"- failure_reasons: `{','.join([str(x) for x in payload.get('failure_reasons', [])])}`")
    qc = payload.get("query_contract", {}) if isinstance(payload.get("query_contract", {}), dict) else {}
    lines.append(f"- query_extractor_launch_total: `{int(qc.get('query_extractor_launch_total', 0) or 0)}`")
    lines.append(f"- query_schedule_extract_requests_total: `{int(qc.get('query_schedule_extract_requests_total', 0) or 0)}`")
    lines.append(f"- query_raw_media_reads_total: `{int(qc.get('query_raw_media_reads_total', 0) or 0)}`")
    qlat = qc.get("query_latency_p95_ms")
    lines.append(f"- query_latency_p95_ms: `{round(float(qlat), 3) if isinstance(qlat, (int, float)) else ''}`")
    qslo = payload.get("queryability_slo", {}) if isinstance(payload.get("queryability_slo", {}), dict) else {}
    if bool(qslo.get("enabled", False)):
        lines.append(f"- queryable_ratio: `{round(float(qslo.get('queryable_ratio', 0.0) or 0.0), 6)}`")
        lines.append(f"- queryable_min_ratio: `{round(float(qslo.get('required_min_ratio', 0.0) or 0.0), 6)}`")
        lines.append(f"- frames_total: `{int(qslo.get('frames_total', 0) or 0)}`")
        lines.append(f"- frames_queryable: `{int(qslo.get('frames_queryable', 0) or 0)}`")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- strict_matrix: `{payload.get('out_path', '')}`")
    lines.append(f"- metrics: `{metrics_path}`")
    lines.append(f"- query_results: `{query_results_path}`")
    lines.append(f"- queryability_coverage: `{coverage_md_path}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real-corpus strict readiness evaluation.")
    parser.add_argument("--contract", default="docs/contracts/real_corpus_expected_answers_v1.json")
    parser.add_argument("--advanced-json", default="")
    parser.add_argument("--generic-json", default="")
    parser.add_argument("--stage1-audit-json", default="")
    parser.add_argument("--advanced-cases", default="docs/query_eval_cases_advanced20.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--latest-report-md", default="docs/reports/real_corpus_strict_latest.md")
    parser.add_argument("--lineage-json", default="")
    parser.add_argument("--min-queryable-ratio", type=float, default=0.0)
    parser.add_argument("--source-tier", choices=["real", "synthetic", "mixed"], default="real")
    args = parser.parse_args(argv)

    contract_path = Path(str(args.contract))
    contract = _load_json(contract_path)
    source_policy = contract.get("strict", {}).get("source_policy", {}) if isinstance(contract.get("strict", {}), dict) else {}
    if not isinstance(source_policy, dict):
        source_policy = {}
    advanced_path = _resolve_report_path_with_policy(
        explicit=str(args.advanced_json),
        pattern="advanced20_*.json",
        latest_name="advanced20_latest.json",
        source_policy=source_policy,
    )
    generic_path = _resolve_report_path_with_policy(
        explicit=str(args.generic_json),
        pattern="generic20_*.json",
        latest_name="generic20_latest.json",
        source_policy=source_policy,
    )
    if not advanced_path.exists():
        print(json.dumps({"ok": False, "error": "advanced_report_not_found", "path": str(advanced_path)}))
        return 2
    if not generic_path.exists():
        print(json.dumps({"ok": False, "error": "generic_report_not_found", "path": str(generic_path)}))
        return 2
    advanced = _load_json(advanced_path)
    generic = _load_json(generic_path)
    strict_summary, strict_rows, strict_failures = _strict_eval(contract=contract, advanced=advanced, generic=generic)
    strict_failure_causes = _strict_failure_cause_summary(strict_rows)
    generic_summary = _generic_eval(generic)

    min_queryable_ratio = float(max(0.0, min(float(args.min_queryable_ratio), 1.0)))
    queryability_slo: dict[str, Any] = {"enabled": bool(min_queryable_ratio > 0.0)}
    if min_queryable_ratio > 0.0:
        lineage_raw = str(args.lineage_json).strip()
        lineage_path = Path(lineage_raw).expanduser() if lineage_raw else _latest_lineage_report()
        if lineage_path is None or not lineage_path.exists():
            queryability_slo.update(
                {
                    "enabled": True,
                    "lineage_report": str(lineage_path) if lineage_path is not None else "",
                    "required_min_ratio": float(min_queryable_ratio),
                    "error": "lineage_report_missing",
                }
            )
            strict_failures.append("queryability_slo_missing")
        else:
            try:
                queryability_slo = _evaluate_queryability_slo(lineage_path=lineage_path, min_ratio=min_queryable_ratio)
                if int(queryability_slo.get("frames_total", 0) or 0) <= 0:
                    strict_failures.append("queryability_slo_no_frames")
                elif float(queryability_slo.get("queryable_ratio", 0.0) or 0.0) < min_queryable_ratio:
                    strict_failures.append("queryability_slo_ratio_below_threshold")
            except Exception as exc:
                queryability_slo.update(
                    {
                        "enabled": True,
                        "lineage_report": str(lineage_path.resolve()),
                        "required_min_ratio": float(min_queryable_ratio),
                        "error": f"lineage_parse_failed:{type(exc).__name__}:{exc}",
                    }
                )
                strict_failures.append("queryability_slo_parse_failed")
    source_tier = _normalize_source_tier(str(args.source_tier))

    if bool(source_policy.get("require_real_corpus", False)):
        disallowed = False
        missing_source = False
        non_real_source_tier = source_tier != "real"
        for payload in (advanced, generic):
            top_src = str(payload.get("source_report") or payload.get("report") or "").strip()
            if not top_src:
                missing_source = True
                break
            if _source_path_disallowed(top_src, source_policy):
                disallowed = True
                break
            rows = payload.get("rows", []) if isinstance(payload.get("rows", []), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_src = str(row.get("source_report") or "").strip()
                if not row_src:
                    missing_source = True
                    break
                if _source_path_disallowed(row_src, source_policy):
                    disallowed = True
                    break
            if disallowed or missing_source:
                break
            payload_source_tier = str(payload.get("source_tier") or "").strip().lower()
            if payload_source_tier and payload_source_tier != "real":
                non_real_source_tier = True
                break
            rows = payload.get("rows", []) if isinstance(payload.get("rows", []), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_source_tier = str(row.get("source_tier") or "").strip().lower()
                if row_source_tier and row_source_tier != "real":
                    non_real_source_tier = True
                    break
            if non_real_source_tier:
                break
        if missing_source:
            strict_failures.append("strict_source_missing")
        if disallowed:
            strict_failures.append("strict_source_disallowed")
        if non_real_source_tier:
            strict_failures.append("strict_source_tier_disallowed")

    strict_query_contract_rows = [row for row in strict_rows if isinstance(row, dict)]
    qc_missing = int(
        len(
            [
                row
                for row in strict_query_contract_rows
                if not bool(row.get("query_contract_metrics_complete", False))
            ]
        )
    )
    query_extractor_launch_total = int(
        sum(
            int(
                (row.get("query_contract_metrics", {}) if isinstance(row.get("query_contract_metrics", {}), dict) else {}).get(
                    "query_extractor_launch_total", 0
                )
                or 0
            )
            for row in strict_query_contract_rows
        )
    )
    query_schedule_extract_requests_total = int(
        sum(
            int(
                (row.get("query_contract_metrics", {}) if isinstance(row.get("query_contract_metrics", {}), dict) else {}).get(
                    "query_schedule_extract_requests_total", 0
                )
                or 0
            )
            for row in strict_query_contract_rows
        )
    )
    query_raw_media_reads_total = int(
        sum(
            int(
                (row.get("query_contract_metrics", {}) if isinstance(row.get("query_contract_metrics", {}), dict) else {}).get(
                    "query_raw_media_reads_total", 0
                )
                or 0
            )
            for row in strict_query_contract_rows
        )
    )
    latency_values = [
        float(row.get("query_latency_total_ms"))
        for row in strict_query_contract_rows
        if isinstance(row.get("query_latency_total_ms"), (int, float))
    ]
    query_latency_p95_ms = _percentile(latency_values, 95.0)
    if qc_missing > 0:
        strict_failures.append("query_contract_metrics_missing")
    if query_extractor_launch_total != 0:
        strict_failures.append("query_contract_extractor_nonzero")
    if query_schedule_extract_requests_total != 0:
        strict_failures.append("query_contract_schedule_requests_nonzero")
    if query_raw_media_reads_total != 0:
        strict_failures.append("query_contract_raw_media_reads_nonzero")
    if query_latency_p95_ms is None:
        strict_failures.append("query_contract_latency_missing")
    elif float(query_latency_p95_ms) > 1500.0:
        strict_failures.append("query_contract_latency_p95_exceeded")
    strict_failures = list(dict.fromkeys([str(x) for x in strict_failures if str(x)]))

    stage1_audit_summary: dict[str, Any] | None = None
    stage1_path = Path(str(args.stage1_audit_json).strip()) if str(args.stage1_audit_json).strip() else None
    if stage1_path and stage1_path.exists():
        try:
            stage1_payload = _load_json(stage1_path)
            stage1_audit_summary = stage1_payload.get("summary", stage1_payload) if isinstance(stage1_payload, dict) else None
        except Exception:
            stage1_audit_summary = {"error": "stage1_audit_parse_failed", "path": str(stage1_path)}

    out_dir = Path(str(args.out_dir).strip()) if str(args.out_dir).strip() else Path("artifacts/real_corpus_gauntlet") / _utc_stamp()
    out_path = Path(str(args.out).strip()) if str(args.out).strip() else out_dir / "strict_matrix.json"
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "metrics.json"
    query_results_path = out_dir / "query_results.json"
    coverage_md_path = out_dir / "queryability_coverage_matrix.md"
    latest_report_md = Path(str(args.latest_report_md).strip() or "docs/reports/real_corpus_strict_latest.md")

    strict_cases = contract.get("strict", {}).get("cases", [])
    if not isinstance(strict_cases, list):
        strict_cases = []
    cases_payload: list[dict[str, Any]] = []
    advanced_cases_path = Path(str(args.advanced_cases).strip())
    if advanced_cases_path.exists():
        try:
            cases_payload = _load_cases(advanced_cases_path)
        except Exception:
            cases_payload = []
    case_lookup = {str(item.get("id") or "").strip(): item for item in cases_payload if isinstance(item, dict)}
    enriched_rows: list[dict[str, Any]] = []
    for row in strict_rows:
        cid = str(row.get("id") or "").strip()
        case = case_lookup.get(cid, {})
        enriched = dict(row)
        enriched["question"] = str(case.get("question") or "")
        enriched["required_signals"] = _required_signals(case)
        enriched_rows.append(enriched)

    payload = {
        "schema_version": 1,
        "ok": len(strict_failures) == 0,
        "strict_mode": True,
        "source_tier": source_tier,
        "strict_contract": str(contract_path.resolve()),
        "strict_contract_sha256": _sha256_file(contract_path),
        "source_reports": {
            "advanced20": str(advanced_path.resolve()),
            "generic20": str(generic_path.resolve()),
        },
        "failure_reasons": strict_failures,
        "generic_policy": contract.get("generic_policy", {}),
        **strict_summary,
        "generic20": generic_summary,
        "query_contract": {
            "rows_with_metrics_missing": int(qc_missing),
            "query_extractor_launch_total": int(query_extractor_launch_total),
            "query_schedule_extract_requests_total": int(query_schedule_extract_requests_total),
            "query_raw_media_reads_total": int(query_raw_media_reads_total),
            "query_latency_p95_ms": float(query_latency_p95_ms) if query_latency_p95_ms is not None else None,
            "query_latency_samples": int(len(latency_values)),
        },
        "queryability_coverage_md": str(coverage_md_path.resolve()),
        "queryability_slo": queryability_slo,
        "strict_failure_causes": strict_failure_causes,
        "strict_failure_cause_counts": strict_failure_causes.get("counts", {}),
    }
    payload["out_path"] = str(out_path.resolve())
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    metrics_payload = {
        "schema_version": 1,
        "strict": {
            "matrix_total": payload["matrix_total"],
            "matrix_evaluated": payload["matrix_evaluated"],
            "matrix_passed": payload["matrix_passed"],
            "matrix_failed": payload["matrix_failed"],
            "matrix_skipped": payload["matrix_skipped"],
            "source_tier": payload["source_tier"],
            "failure_reasons": payload["failure_reasons"],
        },
        "query_contract": {
            "rows_with_metrics_missing": int(qc_missing),
            "query_extractor_launch_total": int(query_extractor_launch_total),
            "query_schedule_extract_requests_total": int(query_schedule_extract_requests_total),
            "query_raw_media_reads_total": int(query_raw_media_reads_total),
            "query_latency_p95_ms": float(query_latency_p95_ms) if query_latency_p95_ms is not None else None,
            "query_latency_samples": int(len(latency_values)),
        },
        "generic20": generic_summary,
        "stage1_audit": stage1_audit_summary or {},
        "strict_failure_causes": strict_failure_causes,
        "queryability_slo": queryability_slo,
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, sort_keys=True), encoding="utf-8")

    query_results_payload = {
        "schema_version": 1,
        "strict_rows": enriched_rows,
        "generic_failed_ids": generic_summary.get("failed_ids", []),
    }
    query_results_path.write_text(json.dumps(query_results_payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_coverage_markdown(path=coverage_md_path, strict_rows=enriched_rows, strict_cases=cases_payload)
    _write_summary_markdown(
        path=latest_report_md,
        payload=payload,
        metrics_path=metrics_path.resolve(),
        query_results_path=query_results_path.resolve(),
        coverage_md_path=coverage_md_path.resolve(),
    )
    payload["latest_report_md"] = str(latest_report_md.resolve())
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": bool(payload.get("ok", False)),
                "output": str(out_path.resolve()),
                "metrics": str(metrics_path.resolve()),
                "query_results": str(query_results_path.resolve()),
                "coverage_md": str(coverage_md_path.resolve()),
                "latest_report_md": str(latest_report_md.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
