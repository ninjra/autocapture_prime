#!/usr/bin/env python3
"""Semantic strict gate for temporal40 reports.

This gate complements count-only strict checks by verifying each answer surface
matches the question intent for its difficulty class.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "for",
    "from",
    "how",
    "if",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "the",
    "then",
    "there",
    "to",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "with",
    "within",
}


TIME_RE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}[t\s]\d{2}:\d{2}(?::\d{2})?)|(?:\b\d{1,2}:\d{2}\s?(?:am|pm)?\b)",
    flags=re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
TOKEN_RE = re.compile(r"[a-z0-9_]+")
ENUM_RE = re.compile(r"^\s*(?:\d+[\.\)]|[-*])\s+")


DIFFICULTY_RULES: dict[str, dict[str, Any]] = {
    "unique_windows_rolling": {"groups": [["window"], ["first_seen", "first seen"], ["last_seen", "last seen"]], "need_time": True, "need_list": 2},
    "unique_domains_seen": {"groups": [["host", "domain", "url"], ["last_seen", "last seen"]], "need_time": True, "need_list": 1},
    "error_toast_inventory": {"groups": [["error", "toast", "dialog"], ["first_seen", "first seen"], ["last_seen", "last seen"], ["duration", "visible_duration"]], "need_time": True},
    "cta_click_inventory": {"groups": [["button", "label"], ["click", "clicked"], ["recent", "most recent"]], "need_time": True},
    "focus_duration_max": {"groups": [["focus", "focused"], ["duration", "seconds"]], "need_number": True},
    "snippet_count_duration": {"groups": [["invoice"], ["frame", "frames"], ["duration"]], "need_number": True},
    "longest_app_session": {"groups": [["slack"], ["longest"], ["start"], ["end"]], "need_time": True},
    "peak_switch_bucket": {"groups": [["interval", "bucket"], ["window", "switch"], ["changes", "count"]], "need_time": True, "need_number": True},
    "click_cadence_median": {"groups": [["median"], ["click"]], "need_number": True},
    "type_to_visible_latency": {"groups": [["incident"], ["latency"], ["typed", "keypress"]], "need_number": True},
    "shortcut_effect": {"groups": [["ctrl", "shortcut"], ["before"], ["after"], ["change"]], "need_time": True},
    "click_navigation_delta": {"groups": [["view details", "details"], ["before"], ["after"], ["url"]], "need_time": True},
    "save_export_dialog": {"groups": [["save", "export"], ["dialog"], ["filename", "file"]], "need_time": True},
    "modal_lifecycle": {"groups": [["modal", "dialog"], ["appear", "appeared"], ["disappear", "dismissed"], ["closed", "click", "key"]], "need_time": True},
    "toggle_transition": {"groups": [["toggle", "checkbox"], ["old", "new", "state"], ["hid", "event"]], "need_time": True},
    "left_right_layout": {"groups": [["left"], ["right"], ["window", "app"]], "need_list": 2},
    "quadrant_new_window": {"groups": [["top-right", "top right", "quadrant"], ["new"], ["window"]], "need_number": True, "need_time": True},
    "banner_latest": {"groups": [["notification", "banner"], ["text"], ["bbox", "bounding"]], "need_time": True},
    "cursor_cross_monitor": {"groups": [["cursor", "mouse"], ["x"], ["start"], ["end"]], "need_time": True},
    "scrollable_visibility": {"groups": [["scrollable", "scrollbar", "scroll"], ["container"], ["position"]]},
    "numeric_min_max_currency": {"groups": [["outlook"], ["min"], ["max"], ["$", "currency", "amount"]], "need_number": True, "need_time": True},
    "percentage_change_event": {"groups": [["percentage", "%"], ["changed", "change"], ["delta"]], "need_number": True, "need_time": True},
    "non_overlay_date_context": {"groups": [["date"], ["context", "window", "app", "element"]], "need_time": True},
    "future_time_string_count": {"groups": [["time-of-day", "time of day", "am", "pm"], ["after"], ["screenshot"]], "need_number": True},
    "identifier_reappearance": {"groups": [["identifier", "regex"], ["first_seen", "first seen"], ["last_seen", "last seen"]], "need_time": True},
    "focus_ancestry_path": {"groups": [["focus", "focused"], ["ancestry", "path"], ["role"], ["name"]], "need_list": 1},
    "click_no_effect": {"groups": [["click"], ["no visible effect", "no effect"], ["no"], ["change"]], "need_time": True},
    "auto_refresh_without_input": {"groups": [["without", "no"], ["hid", "input"], ["changed", "change"]], "need_time": True},
    "paste_like_jump": {"groups": [["paste"], ["jumped", "jump"], ["chars", "characters"], ["field"]], "need_number": True, "need_time": True},
    "most_clicked_role": {"groups": [["role"], ["click"], ["count"]], "need_number": True},
    "state_to_state_reconstruction": {"groups": [["open invoice"], ["state changed"], ["sequence", "actions"]], "need_time": True, "need_list": 2},
    "search_and_result": {"groups": [["search"], ["term"], ["result"]], "need_time": True},
    "scroll_delta_vs_position": {"groups": [["scroll"], ["delta"], ["position"]], "need_number": True},
    "copy_paste_sequence": {"groups": [["copy"], ["paste"], ["target"]], "need_time": True},
    "new_tab_shortcut": {"groups": [["ctrl+t", "ctrl+n", "shortcut"], ["tab", "window"], ["title", "url"]], "need_time": True},
    "hover_tooltip": {"groups": [["tooltip"], ["hover"], ["appear"], ["disappear"]], "need_time": True},
    "context_menu_right_click": {"groups": [["context menu", "menu"], ["right-click", "right click"], ["selected", "item"]], "need_time": True},
    "uia_vs_rendered_discrepancy": {"groups": [["uia"], ["rendered"], ["disagree", "mismatch", "discrepancy"], ["strings"]], "need_time": True},
    "vector_similarity_across_time": {"groups": [["vector"], ["similar"], ["pair"], ["changed"]], "need_time": True},
    "leave_return_state_fingerprint": {"groups": [["leave"], ["return"], ["time away", "away"], ["state"]], "need_time": True},
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _core_bullets(bullets: list[str]) -> list[str]:
    out: list[str] = []
    for raw in bullets:
        text = str(raw or "").strip()
        if not text:
            continue
        low = text.casefold()
        if low.startswith("support:") or low.startswith("source:"):
            continue
        out.append(text)
    return out


def _tokenize(text: str) -> set[str]:
    return {m.group(0) for m in TOKEN_RE.finditer(str(text or "").casefold()) if len(m.group(0)) >= 3}


def _has_term(raw_text: str, tokens: set[str], term: str) -> bool:
    needle = str(term or "").strip().casefold()
    if not needle:
        return False
    if " " in needle or "-" in needle or "+" in needle or "/" in needle:
        return needle in raw_text
    return needle in tokens


def _lexical_overlap(question: str, answer_text: str) -> float:
    q_tokens = _tokenize(question)
    q_tokens = {tok for tok in q_tokens if tok not in STOPWORDS}
    if not q_tokens:
        return 1.0
    a_tokens = _tokenize(answer_text)
    overlap = len(q_tokens.intersection(a_tokens))
    return float(overlap / max(1, len(q_tokens)))


def _citations_present(row: dict[str, Any]) -> bool:
    providers = row.get("providers", [])
    if not isinstance(providers, list):
        return False
    for item in providers:
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("citation_count", 0) or 0) > 0:
                return True
        except Exception:
            continue
    return False


def evaluate_row(case: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("id") or "")
    difficulty = str(case.get("difficulty_class") or "")
    question = str(case.get("question") or "")
    summary = str(row.get("summary") or "")
    bullets = _core_bullets(row.get("bullets", []) if isinstance(row.get("bullets"), list) else [])
    text = "\n".join([summary, *bullets]).strip()
    text_low = text.casefold()
    tokens = _tokenize(text_low)
    rules = DIFFICULTY_RULES.get(difficulty, {})
    groups = rules.get("groups", []) if isinstance(rules.get("groups"), list) else []

    reasons: list[str] = []
    group_rows: list[dict[str, Any]] = []
    answer_state = str(row.get("answer_state") or "").casefold().strip()
    degraded_state = answer_state in {"partial", "no_evidence"}
    degraded_markers = (
        "indeterminate",
        "not available yet",
        "no temporal aggregate",
        "insufficient evidence",
        "no temporal evidence",
        "incomplete",
    )

    if answer_state not in {"ok", "partial", "no_evidence"}:
        reasons.append("answer_state_invalid")
    if not text:
        reasons.append("answer_surface_empty")
    if answer_state == "ok" and not _citations_present(row):
        reasons.append("citations_missing")

    overlap = _lexical_overlap(question, text_low)
    overlap_min = 0.12 if degraded_state else 0.18
    if overlap < overlap_min:
        reasons.append("lexical_overlap_low")

    matched_groups = 0
    for idx, raw_group in enumerate(groups):
        alts = [str(x).strip() for x in raw_group if str(x).strip()] if isinstance(raw_group, list) else []
        matched = ""
        for alt in alts:
            if _has_term(text_low, tokens, alt):
                matched = alt
                break
        ok = bool(matched)
        group_rows.append({"idx": idx, "alternatives": alts, "matched": matched, "ok": ok})
        if ok:
            matched_groups += 1
        if (not degraded_state) and (not ok):
            reasons.append(f"semantic_group_missing:{idx}")

    if degraded_state:
        if not any(marker in text_low for marker in degraded_markers):
            reasons.append("degraded_marker_missing")
        if matched_groups <= 0:
            reasons.append("degraded_semantic_alignment_missing")
    else:
        if bool(rules.get("need_time")) and not bool(TIME_RE.search(text)):
            reasons.append("time_evidence_missing")
        if bool(rules.get("need_number")) and not bool(NUMBER_RE.search(text)):
            reasons.append("numeric_evidence_missing")
        min_list = int(rules.get("need_list", 0) or 0)
        if min_list > 0:
            enumerated = sum(1 for line in bullets if ENUM_RE.search(line))
            if enumerated < min_list:
                reasons.append("list_evidence_missing")

    ok = len(reasons) == 0
    return {
        "id": case_id,
        "difficulty_class": difficulty,
        "answer_state": answer_state,
        "degraded_state": degraded_state,
        "ok": ok,
        "reasons": reasons,
        "overlap": round(float(overlap), 4),
        "summary": summary,
        "groups": group_rows,
    }


def missing_rule_classes(cases: list[dict[str, Any]]) -> list[str]:
    values: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            continue
        cls = str(case.get("difficulty_class") or "").strip()
        if cls:
            values.add(cls)
    return sorted(cls for cls in values if cls not in DIFFICULTY_RULES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semantic strict gate for temporal40 output.")
    parser.add_argument("--report", required=True, help="Path to temporal40 run report JSON.")
    parser.add_argument("--cases", required=True, help="Path to temporal40 cases JSON.")
    parser.add_argument("--output", default="artifacts/temporal40/temporal40_semantic_gate.json")
    parser.add_argument("--expected-passed", type=int, default=40)
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    cases_path = Path(args.cases)
    payload = _load_json(report_path)
    cases_any = _load_json(cases_path)

    if not isinstance(payload, dict):
        raise SystemExit("report must be a JSON object")
    if not isinstance(cases_any, list):
        raise SystemExit("cases must be a JSON array")

    cases = [row for row in cases_any if isinstance(row, dict)]
    missing_rules = missing_rule_classes(cases)

    rows_by_id: dict[str, dict[str, Any]] = {}
    rows_any = payload.get("rows", [])
    if isinstance(rows_any, list):
        for row in rows_any:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id") or "").strip()
            if row_id:
                rows_by_id[row_id] = row

    sem_rows: list[dict[str, Any]] = []
    reasons_counter: Counter[str] = Counter()
    for case in cases:
        case_id = str(case.get("id") or "").strip()
        row = rows_by_id.get(case_id)
        if row is None:
            sem = {"id": case_id, "difficulty_class": str(case.get("difficulty_class") or ""), "ok": False, "reasons": ["row_missing"], "overlap": 0.0, "summary": "", "groups": []}
        else:
            sem = evaluate_row(case, row)
        sem_rows.append(sem)
        for reason in sem.get("reasons", []):
            reasons_counter[str(reason)] += 1

    semantic_passed = sum(1 for row in sem_rows if bool(row.get("ok", False)))
    semantic_failed = len(sem_rows) - semantic_passed
    expected_passed = int(args.expected_passed)
    ok = semantic_passed == expected_passed and semantic_failed == max(0, len(sem_rows) - expected_passed) and not missing_rules

    out = {
        "schema_version": 1,
        "ok": bool(ok),
        "report": str(report_path.resolve()),
        "cases": str(cases_path.resolve()),
        "counts": {
            "evaluated": len(sem_rows),
            "semantic_passed": semantic_passed,
            "semantic_failed": semantic_failed,
            "expected_passed": expected_passed,
        },
        "missing_rule_classes": missing_rules,
        "top_failure_reasons": reasons_counter.most_common(10),
        "rows": sem_rows,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(ok), "output": str(out_path.resolve())}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
