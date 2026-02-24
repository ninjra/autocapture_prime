#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _load_rows(path: Path, suite: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["_suite"] = suite
        out.append(item)
    return out


def _core_bullets(row: dict[str, Any]) -> list[str]:
    bullets = row.get("bullets", [])
    out: list[str] = []
    if not isinstance(bullets, list):
        return out
    for raw in bullets:
        text = str(raw or "").strip()
        if not text:
            continue
        low = text.casefold()
        if low.startswith("source:") or low.startswith("support:"):
            continue
        out.append(text)
    return out


def _support_text(row: dict[str, Any]) -> str:
    bullets = row.get("bullets", [])
    if not isinstance(bullets, list):
        return ""
    parts: list[str] = []
    for raw in bullets:
        text = str(raw or "").strip()
        if text.casefold().startswith("support:"):
            parts.append(text)
    return "\n".join(parts)


def _enumerated_lines(core_bullets: list[str]) -> list[str]:
    return [line for line in core_bullets if re.match(r"^\d+\.\s+", line)]


def _has_timestamp(text: str) -> bool:
    raw = str(text or "")
    if re.search(r"\b\d{1,2}:\d{2}\b", raw):
        return True
    return bool(
        re.search(
            r"\b(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
            raw,
            flags=re.IGNORECASE,
        )
    )


def _extract_console_counts(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("red_count", "green_count", "other_count"):
        m = re.search(rf"\b{re.escape(key)}\s*=\s*(\d+)", text, flags=re.IGNORECASE)
        if m:
            out[key] = int(m.group(1))
    return out


def _extract_summary_counts(summary: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("count_red", "count_green", "count_other"):
        m = re.search(rf"\b{re.escape(key)}\s*=\s*(\d+)", summary, flags=re.IGNORECASE)
        if m:
            out[key] = int(m.group(1))
    return out


def _issue(row: dict[str, Any], code: str, detail: str) -> dict[str, Any]:
    return {
        "suite": str(row.get("_suite") or ""),
        "id": str(row.get("id") or row.get("case_id") or ""),
        "code": code,
        "detail": detail,
        "question": str(row.get("question") or ""),
        "summary": str(row.get("summary") or ""),
        "state": str(row.get("answer_state") or ""),
        "passed": bool(row.get("passed", False)),
    }


def audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in rows:
        if not bool(row.get("passed", False)):
            continue
        question = str(row.get("question") or "")
        summary = str(row.get("summary") or "")
        state = str(row.get("answer_state") or "")
        case_id = str(row.get("id") or row.get("case_id") or "").strip().upper()
        core = _core_bullets(row)

        if state != "ok":
            issues.append(_issue(row, "state_not_ok", f"answer_state={state}"))

        if "first 5 visible" in question.casefold():
            enumerated = _enumerated_lines(core)
            if len(enumerated) < 5:
                issues.append(
                    _issue(
                        row,
                        "insufficient_list_items",
                        f"required>=5_enumerated_items got={len(enumerated)}",
                    )
                )

        if "last two visible messages" in question.casefold():
            enumerated = _enumerated_lines(core)
            if len(enumerated) < 2:
                issues.append(
                    _issue(
                        row,
                        "missing_message_rows",
                        f"required>=2_enumerated_message_rows got={len(enumerated)}",
                    )
                )
            else:
                missing_ts = [line for line in enumerated[:2] if not _has_timestamp(line)]
                if missing_ts:
                    issues.append(
                        _issue(
                            row,
                            "message_timestamp_missing",
                            f"missing_timestamp_in_rows={len(missing_ts)}",
                        )
                    )

        if case_id in {"Q5", "GQ5"}:
            labels: list[str] = []
            for line in core:
                m = re.match(r"^\d+\.\s*([^:]{1,80}):", line)
                if m:
                    labels.append(m.group(1).strip().casefold())
            dupes = sorted({x for x in labels if labels.count(x) > 1})
            if dupes:
                issues.append(_issue(row, "duplicate_field_labels", f"labels={dupes}"))

        if case_id in {"Q9", "GQ9"}:
            summary_counts = _extract_summary_counts(summary)
            support_counts = _extract_console_counts(_support_text(row))
            if summary_counts and support_counts:
                mapped = {
                    "count_red": support_counts.get("red_count"),
                    "count_green": support_counts.get("green_count"),
                    "count_other": support_counts.get("other_count"),
                }
                mismatched = {
                    key: {"summary": summary_counts.get(key), "support": mapped.get(key)}
                    for key in ("count_red", "count_green", "count_other")
                    if summary_counts.get(key) is not None and mapped.get(key) is not None and summary_counts.get(key) != mapped.get(key)
                }
                if mismatched:
                    issues.append(_issue(row, "count_mismatch_summary_vs_support", json.dumps(mismatched, sort_keys=True)))

        if case_id in {"Q10", "GQ10"}:
            bad_tab_rows = [line for line in core if "active_tab=0https://" in line or "active_tab=http" in line]
            if bad_tab_rows:
                issues.append(_issue(row, "invalid_active_tab_value", f"rows={len(bad_tab_rows)}"))

    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit Q40 pass rows for likely false-positive correctness.")
    ap.add_argument("--advanced-json", default="artifacts/advanced10/advanced20_latest.json")
    ap.add_argument("--generic-json", default="artifacts/advanced10/generic20_latest.json")
    ap.add_argument("--out-json", default="artifacts/advanced10/q40_quality_audit_latest.json")
    args = ap.parse_args()

    adv_path = Path(args.advanced_json)
    gen_path = Path(args.generic_json)
    out_path = Path(args.out_json)

    rows = _load_rows(adv_path, "advanced20") + _load_rows(gen_path, "generic20")
    issues = audit_rows(rows)
    by_code: dict[str, int] = {}
    for row in issues:
        code = str(row.get("code") or "")
        by_code[code] = by_code.get(code, 0) + 1

    payload = {
        "ok": len(issues) == 0,
        "advanced_json": str(adv_path),
        "generic_json": str(gen_path),
        "issues_total": len(issues),
        "issue_counts": by_code,
        "issues": issues,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "issues_total": len(issues), "out": str(out_path), "issue_counts": by_code}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
