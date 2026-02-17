#!/usr/bin/env python3
"""Evaluate combined 40-question matrix from advanced20 + generic20 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_matching(pattern: str) -> Path | None:
    root = Path("artifacts/advanced10")
    if not root.exists():
        return None
    found = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def _is_nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _generic_contract_check(row: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
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
    return len(errors) == 0, errors


def _summarize_advanced(adv: dict[str, Any]) -> dict[str, Any]:
    rows = adv.get("rows", []) if isinstance(adv.get("rows", []), list) else []
    failed_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ev = row.get("expected_eval", {}) if isinstance(row.get("expected_eval", {}), dict) else {}
        if not bool(ev.get("passed", False)):
            failed_ids.append(str(row.get("id") or ""))
    return {
        "artifact": str(adv.get("__path", "")),
        "total": int(len(rows)),
        "passed": int(adv.get("evaluated_passed", 0) or 0),
        "failed": int(adv.get("evaluated_failed", 0) or 0),
        "failed_ids": [x for x in failed_ids if x],
        "ok": int(adv.get("evaluated_failed", 0) or 0) == 0 and int(adv.get("evaluated_total", 0) or 0) == len(rows),
    }


def _summarize_generic(gen: dict[str, Any]) -> dict[str, Any]:
    rows = gen.get("rows", []) if isinstance(gen.get("rows", []), list) else []
    failed_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    passed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ok, errors = _generic_contract_check(row)
        if ok:
            passed += 1
            continue
        cid = str(row.get("id") or "")
        failed_ids.append(cid)
        failures.append({"id": cid, "errors": errors})
    total = len(rows)
    return {
        "artifact": str(gen.get("__path", "")),
        "total": int(total),
        "passed": int(passed),
        "failed": int(max(0, total - passed)),
        "failed_ids": [x for x in failed_ids if x],
        "failures": failures,
        "ok": int(passed) == int(total) and total > 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--advanced-json", default="", help="Path to advanced20 artifact JSON.")
    parser.add_argument("--generic-json", default="", help="Path to generic20 artifact JSON.")
    parser.add_argument("--out", default="artifacts/advanced10/q40_matrix_latest.json", help="Output summary JSON.")
    args = parser.parse_args(argv)

    adv_path = Path(str(args.advanced_json).strip()) if str(args.advanced_json).strip() else (_latest_matching("advanced20_*.json") or Path(""))
    gen_path = Path(str(args.generic_json).strip()) if str(args.generic_json).strip() else (_latest_matching("generic20_*.json") or Path(""))
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
    total = int(adv_summary["total"]) + int(gen_summary["total"])
    passed = int(adv_summary["passed"]) + int(gen_summary["passed"])
    failed = int(total - passed)
    out_payload = {
        "ok": bool(adv_summary["ok"] and gen_summary["ok"]),
        "matrix_total": int(total),
        "matrix_passed": int(passed),
        "matrix_failed": int(failed),
        "advanced20": adv_summary,
        "generic20_contract": gen_summary,
    }
    out_path = Path(str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "matrix_total": total, "matrix_failed": failed}))
    return 0 if bool(out_payload["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
