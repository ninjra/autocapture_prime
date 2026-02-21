#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROVIDER_KEYS = {
    "positive_provider_contribution",
    "non_disallowed_positive_provider_contribution",
    "disallowed_answer_provider_activity",
    "metadata_only_query",
    "promptops_used",
    "hard_vlm_structured",
    "synth_provider_in_path",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _failed_checks(row: dict[str, Any]) -> list[dict[str, Any]]:
    eval_obj = row.get("expected_eval", {}) if isinstance(row.get("expected_eval"), dict) else {}
    checks = eval_obj.get("checks", []) if isinstance(eval_obj.get("checks"), list) else []
    out: list[dict[str, Any]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        if "present" in item and not bool(item.get("present", False)):
            out.append(item)
            continue
        if "match" in item and not bool(item.get("match", False)):
            out.append(item)
    return out


def _provider_stats(row: dict[str, Any]) -> dict[str, Any]:
    providers = row.get("providers", [])
    rows = providers if isinstance(providers, list) else []
    citation_total = 0
    contribution_total = 0
    provider_ids: list[str] = []
    doc_kinds: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("provider_id") or "").strip()
        if provider_id:
            provider_ids.append(provider_id)
        citation_total += int(item.get("citation_count", 0) or 0)
        contribution_total += int(item.get("contribution_bp", 0) or 0)
        kinds = item.get("doc_kinds", [])
        if isinstance(kinds, list):
            for kind in kinds:
                token = str(kind or "").strip()
                if token:
                    doc_kinds.add(token)
    return {
        "citation_total": int(citation_total),
        "contribution_bp_total": int(contribution_total),
        "provider_ids": sorted(set(provider_ids)),
        "doc_kinds": sorted(doc_kinds),
    }


def _classify(row: dict[str, Any]) -> tuple[str, str]:
    if bool(row.get("skipped", False)):
        return "missing_evidence", "row_skipped"
    failed_checks = _failed_checks(row)
    pstats = _provider_stats(row)
    citation_total = int(pstats["citation_total"])

    provider_inconsistency = any(
        str(chk.get("key") or "") in PROVIDER_KEYS
        or (
            str(chk.get("type") or "") == "pipeline_enforcement"
            and ("provider" in str(chk.get("key") or "") or "metadata_only_query" == str(chk.get("key") or ""))
        )
        for chk in failed_checks
    )
    if provider_inconsistency:
        return "provider_path_inconsistency", "provider_or_path_contract_failed"

    has_expected_answer_mismatch = any(
        str(chk.get("type") or "") == "expected_answer"
        and (not bool(chk.get("match", True)) or str(chk.get("mode") or "") in {"missing_structured_path", "structured_exact"})
        for chk in failed_checks
    )
    has_other_mismatch = any(
        str(chk.get("type") or "") in {"contains_all", "contains_any", "path", "strict_numeric", "strict_quality"}
        for chk in failed_checks
    )

    if citation_total <= 0:
        return "missing_evidence", "no_positive_evidence_trace"
    if has_expected_answer_mismatch:
        return "exact_answer_mismatch", "structured_expected_answer_not_exact"
    if has_other_mismatch:
        return "evidence_present_but_nonmatching", "evidence_available_but_expected_tokens_not_met"
    return "exact_answer_mismatch", "failed_without_specific_signal"


def _iter_failed_rows(payload: dict[str, Any], suite: str) -> list[dict[str, Any]]:
    rows = payload.get("rows", []) if isinstance(payload.get("rows"), list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        eval_obj = row.get("expected_eval", {}) if isinstance(row.get("expected_eval"), dict) else {}
        passed = bool(eval_obj.get("passed", row.get("passed", False)))
        skipped = bool(row.get("skipped", False) or eval_obj.get("skipped", False))
        ok = bool(row.get("ok", False))
        if skipped or (not passed) or (not ok):
            category, reason = _classify(row)
            stats = _provider_stats(row)
            out.append(
                {
                    "suite": suite,
                    "id": str(row.get("id") or ""),
                    "question": str(row.get("question") or ""),
                    "category": category,
                    "reason": reason,
                    "skipped": bool(skipped),
                    "ok": bool(ok),
                    "passed": bool(passed),
                    "summary": str(row.get("summary") or ""),
                    "failed_checks": _failed_checks(row),
                    "provider_ids": stats["provider_ids"],
                    "doc_kinds": stats["doc_kinds"],
                    "citation_total": int(stats["citation_total"]),
                    "contribution_bp_total": int(stats["contribution_bp_total"]),
                }
            )
    return out


def _to_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Q40 UIA Mismatch Report",
        "",
        f"- generated_utc: {payload.get('generated_utc')}",
        f"- total_failures: {payload.get('total_failures')}",
        f"- category_counts: {json.dumps(payload.get('category_counts', {}), sort_keys=True)}",
        "",
        "| suite | id | category | reason | citation_total | providers |",
        "|---|---|---|---|---:|---|",
    ]
    for row in payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        providers = ",".join(str(x) for x in (row.get("provider_ids") or []))
        lines.append(
            f"| {row.get('suite')} | {row.get('id')} | {row.get('category')} | {row.get('reason')} | {row.get('citation_total')} | {providers} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_report(advanced: dict[str, Any], generic: dict[str, Any], matrix: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _iter_failed_rows(advanced, "advanced20") + _iter_failed_rows(generic, "generic20")
    counts: dict[str, int] = {}
    for row in rows:
        category = str(row.get("category") or "unknown")
        counts[category] = int(counts.get(category, 0)) + 1
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_failures": int(len(rows)),
        "category_counts": counts,
        "matrix": matrix or {},
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify Q40 mismatch rows by strict correctness taxonomy.")
    parser.add_argument("--advanced-json", required=True)
    parser.add_argument("--generic-json", required=True)
    parser.add_argument("--matrix-json", default="")
    parser.add_argument("--out-json", default="artifacts/advanced10/q40_uia_mismatch_latest.json")
    parser.add_argument("--out-md", default="docs/reports/q40_uia_mismatch_latest.md")
    args = parser.parse_args(argv)

    adv = _load(Path(args.advanced_json))
    gen = _load(Path(args.generic_json))
    matrix: dict[str, Any] | None = None
    if str(args.matrix_json or "").strip():
        matrix = _load(Path(args.matrix_json))

    report = generate_report(adv, gen, matrix)
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(_to_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out_json": str(out_json),
                "out_md": str(out_md),
                "total_failures": int(report.get("total_failures", 0)),
                "category_counts": report.get("category_counts", {}),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
