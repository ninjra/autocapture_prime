#!/usr/bin/env python3
"""Evaluate combined 40-question matrix from advanced20 + generic20 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STRICT_DISALLOWED_ANSWER_PROVIDERS = frozenset(
    {
        "builtin.answer.synth_vllm_localhost",
        "hard_vlm.direct",
    }
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_matching(pattern: str) -> Path | None:
    root = Path("artifacts/advanced10")
    if not root.exists():
        return None
    found = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def _resolve_default_input_path(*, explicit: str, latest_name: str, pattern: str) -> Path:
    if str(explicit).strip():
        return Path(str(explicit).strip())
    root = Path("artifacts/advanced10")
    latest = root / latest_name
    if latest.exists():
        return latest
    return _latest_matching(pattern) or Path("")


def _is_nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _artifact_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows", []) if isinstance(payload.get("rows", []), list) else []
    paths: set[str] = set()
    shas: set[str] = set()
    run_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("source_report") or "").strip()
        sha = str(row.get("source_report_sha256") or "").strip()
        run_id = str(row.get("source_report_run_id") or "").strip()
        if path:
            paths.add(path)
        if sha:
            shas.add(sha)
        if run_id:
            run_ids.add(run_id)
    top_path = str(payload.get("source_report") or payload.get("report") or "").strip()
    top_sha = str(payload.get("source_report_sha256") or "").strip()
    top_run_id = str(payload.get("source_report_run_id") or "").strip()
    if top_path:
        paths.add(top_path)
    if top_sha:
        shas.add(top_sha)
    if top_run_id:
        run_ids.add(top_run_id)
    path_values = sorted(paths)
    sha_values = sorted(shas)
    run_values = sorted(run_ids)
    path_consistent = len(path_values) <= 1
    sha_consistent = len(sha_values) <= 1
    run_consistent = len(run_values) <= 1
    has_minimum = bool(sha_values and (path_values or run_values))
    return {
        "path": path_values[0] if len(path_values) == 1 else "",
        "sha256": sha_values[0] if len(sha_values) == 1 else "",
        "run_id": run_values[0] if len(run_values) == 1 else "",
        "path_values": path_values,
        "sha_values": sha_values,
        "run_id_values": run_values,
        "path_consistent": bool(path_consistent),
        "sha_consistent": bool(sha_consistent),
        "run_id_consistent": bool(run_consistent),
        "consistent": bool(path_consistent and sha_consistent and run_consistent),
        "has_minimum": bool(has_minimum),
    }


def _generic_contract_check(row: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if bool(row.get("skipped", False)):
        return True, errors
    if not bool(row.get("ok", False)):
        errors.append("query_failed")
    if not _is_nonempty(row.get("query_run_id")):
        errors.append("missing_query_run_id")
    if not _is_nonempty(row.get("summary")):
        errors.append("missing_summary")
    answer_state = str(row.get("answer_state") or "").strip()
    if answer_state not in {"ok", "partial", "no_evidence"}:
        errors.append("invalid_answer_state")
    eval_obj = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
    if not bool(eval_obj.get("passed", False)):
        errors.append("expected_eval_failed")
    providers = row.get("providers", [])
    if answer_state == "ok" and (not isinstance(providers, list) or len(providers) == 0):
        errors.append("ok_without_provider_contributions")
    provider_rows = providers if isinstance(providers, list) else []
    positive_provider_ids: list[str] = []
    non_disallowed_positive_ids: list[str] = []
    disallowed_active = False
    for item in provider_rows:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("provider_id") or "").strip()
        if not provider_id:
            continue
        contribution_bp = int(item.get("contribution_bp", 0) or 0)
        claim_count = int(item.get("claim_count", 0) or 0)
        citation_count = int(item.get("citation_count", 0) or 0)
        if contribution_bp > 0:
            positive_provider_ids.append(provider_id)
            if provider_id not in STRICT_DISALLOWED_ANSWER_PROVIDERS:
                non_disallowed_positive_ids.append(provider_id)
        if provider_id in STRICT_DISALLOWED_ANSWER_PROVIDERS and (
            contribution_bp > 0 or claim_count > 0 or citation_count > 0
        ):
            disallowed_active = True
    if answer_state == "ok" and not positive_provider_ids:
        errors.append("ok_without_positive_provider_contribution")
    if answer_state == "ok" and not non_disallowed_positive_ids:
        errors.append("ok_without_non_disallowed_positive_provider_contribution")
    if disallowed_active:
        errors.append("disallowed_answer_provider_activity")
    return len(errors) == 0, errors


def _advanced_contract_errors(row: dict[str, Any]) -> list[str]:
    ev = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
    if bool(ev.get("passed", False)):
        return []
    errors: list[str] = []
    if not bool(ev.get("evaluated", False)):
        errors.append("expected_eval_not_evaluated")
    reasons = ev.get("reasons", []) if isinstance(ev.get("reasons", []), list) else []
    for reason in reasons:
        txt = str(reason or "").strip()
        if txt:
            errors.append(f"expected_eval_reason:{txt}")
    checks = ev.get("checks", []) if isinstance(ev.get("checks", []), list) else []
    for check in checks:
        if not isinstance(check, dict):
            continue
        if bool(check.get("present", True)):
            continue
        key = str(check.get("key") or check.get("path") or check.get("type") or "").strip()
        expected = str(check.get("expected") or check.get("equals") or "").strip()
        if key and expected:
            errors.append(f"missing:{key}={expected}")
        elif key:
            errors.append(f"missing:{key}")
    if not errors:
        errors.append("expected_eval_failed")
    return list(dict.fromkeys([str(x) for x in errors if str(x)]))


def _summarize_advanced(adv: dict[str, Any]) -> dict[str, Any]:
    rows = adv.get("rows", []) if isinstance(adv.get("rows", []), list) else []
    failed_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    skipped = int(adv.get("rows_skipped", 0) or 0)
    if skipped <= 0:
        for row in rows:
            if not isinstance(row, dict):
                continue
            ev_row = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
            if bool(row.get("skipped", False)) or bool(ev_row.get("skipped", False)):
                skipped += 1
    for row in rows:
        if not isinstance(row, dict):
            continue
        ev_row = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
        if bool(row.get("skipped", False)) or bool(ev_row.get("skipped", False)):
            continue
        ev = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
        if not bool(ev.get("passed", False)):
            cid = str(row.get("id") or "")
            failed_ids.append(cid)
            failures.append({"id": cid, "errors": _advanced_contract_errors(row)})
    evaluated_total = int(adv.get("evaluated_total", max(0, len(rows) - skipped)) or 0)
    passed = int(adv.get("evaluated_passed", max(0, evaluated_total - len(failed_ids))) or 0)
    failed = int(max(0, evaluated_total - passed))
    return {
        "artifact": str(adv.get("__path", "")),
        "total": int(len(rows)),
        "evaluated": int(evaluated_total),
        "passed": int(passed),
        "failed": int(failed),
        "skipped": int(skipped),
        "failed_ids": [x for x in failed_ids if x],
        "failures": failures,
        "ok": int(failed) == 0 and int(evaluated_total + skipped) == int(len(rows)),
    }


def _summarize_generic(gen: dict[str, Any]) -> dict[str, Any]:
    rows = gen.get("rows", []) if isinstance(gen.get("rows", []), list) else []
    failed_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    passed = 0
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if bool(row.get("skipped", False)):
            skipped += 1
            continue
        ok, errors = _generic_contract_check(row)
        if ok:
            passed += 1
            continue
        cid = str(row.get("id") or "")
        failed_ids.append(cid)
        failures.append({"id": cid, "errors": errors})
    total = len(rows)
    evaluated = max(0, total - skipped)
    failed = int(max(0, evaluated - passed))
    return {
        "artifact": str(gen.get("__path", "")),
        "total": int(total),
        "evaluated": int(evaluated),
        "passed": int(passed),
        "failed": int(failed),
        "skipped": int(skipped),
        "failed_ids": [x for x in failed_ids if x],
        "failures": failures,
        "ok": int(failed) == 0 and int(evaluated + skipped) == int(total) and total > 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--advanced-json", default="", help="Path to advanced20 artifact JSON.")
    parser.add_argument("--generic-json", default="", help="Path to generic20 artifact JSON.")
    parser.add_argument("--out", default="artifacts/advanced10/q40_matrix_latest.json", help="Output summary JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Fail closed when any matrix row is skipped (strict golden mode).",
    )
    parser.add_argument(
        "--expected-total",
        type=int,
        default=0,
        help="Optional expected matrix size; strict mode fails when total/evaluated mismatch this value.",
    )
    parser.add_argument(
        "--source-tier",
        default="real",
        choices=("real", "synthetic"),
        help="Provenance tier for this matrix output.",
    )
    args = parser.parse_args(argv)

    adv_path = _resolve_default_input_path(
        explicit=str(args.advanced_json),
        latest_name="advanced20_latest.json",
        pattern="advanced20_*.json",
    )
    gen_path = _resolve_default_input_path(
        explicit=str(args.generic_json),
        latest_name="generic20_latest.json",
        pattern="generic20_*.json",
    )
    if not adv_path.exists():
        print(json.dumps({"ok": False, "error": "advanced20_not_found", "path": str(adv_path)}))
        return 2
    if not gen_path.exists():
        print(json.dumps({"ok": False, "error": "generic20_not_found", "path": str(gen_path)}))
        return 2

    adv = _load(adv_path)
    gen = _load(gen_path)
    adv["__path"] = str(adv_path)
    gen["__path"] = str(gen_path)

    adv_summary = _summarize_advanced(adv)
    gen_summary = _summarize_generic(gen)
    adv_provenance = _artifact_provenance(adv)
    gen_provenance = _artifact_provenance(gen)
    total = int(adv_summary["total"]) + int(gen_summary["total"])
    passed = int(adv_summary["passed"]) + int(gen_summary["passed"])
    skipped = int(adv_summary.get("skipped", 0)) + int(gen_summary.get("skipped", 0))
    failed = int(adv_summary["failed"]) + int(gen_summary["failed"])
    evaluated = int(total - skipped)
    strict = bool(args.strict)
    expected_total = max(0, int(args.expected_total))
    failure_reasons: list[str] = []
    if int(failed) > 0:
        failure_reasons.append("matrix_failed_nonzero")
    if int(evaluated) <= 0:
        failure_reasons.append("matrix_evaluated_zero")
    if strict and int(skipped) > 0:
        failure_reasons.append("strict_matrix_skipped_nonzero")
    if strict and expected_total > 0 and int(total) != int(expected_total):
        failure_reasons.append("strict_matrix_total_mismatch")
    if strict and expected_total > 0 and int(evaluated) != int(expected_total):
        failure_reasons.append("strict_matrix_evaluated_mismatch")
    if strict and (not bool(adv_provenance.get("has_minimum", False)) or not bool(gen_provenance.get("has_minimum", False))):
        failure_reasons.append("strict_provenance_missing")
    if strict and (not bool(adv_provenance.get("consistent", False)) or not bool(gen_provenance.get("consistent", False))):
        failure_reasons.append("strict_provenance_artifact_inconsistent")
    adv_sha = str(adv_provenance.get("sha256") or "").strip()
    gen_sha = str(gen_provenance.get("sha256") or "").strip()
    if strict and adv_sha and gen_sha and adv_sha != gen_sha:
        failure_reasons.append("strict_provenance_mismatch")

    out_payload = {
        "ok": bool(adv_summary["ok"] and gen_summary["ok"] and len(failure_reasons) == 0),
        "source_tier": str(args.source_tier),
        "strict_mode": strict,
        "expected_total": int(expected_total),
        "failure_reasons": [str(reason) for reason in failure_reasons],
        "matrix_total": int(total),
        "matrix_evaluated": int(evaluated),
        "matrix_passed": int(passed),
        "matrix_failed": int(failed),
        "matrix_skipped": int(skipped),
        "advanced20": adv_summary,
        "generic20_contract": gen_summary,
        "provenance": {
            "advanced20": adv_provenance,
            "generic20": gen_provenance,
        },
    }
    out_path = Path(str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": bool(out_payload["ok"]),
                "out": str(out_path),
                "matrix_total": total,
                "matrix_failed": failed,
                "failure_reasons": out_payload["failure_reasons"],
            }
        )
    )
    return 0 if bool(out_payload["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
