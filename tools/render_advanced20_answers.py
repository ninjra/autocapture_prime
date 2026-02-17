#!/usr/bin/env python3
"""Render a concise advanced20 answer+proof report from an eval artifact."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any


def _latest_advanced20() -> Path:
    paths = sorted(glob.glob("artifacts/advanced10/advanced20_*.json"))
    if not paths:
        return Path("")
    return Path(paths[-1])


def _check_score(checks: list[dict[str, Any]]) -> tuple[int, int]:
    ok = 0
    total = 0
    for c in checks:
        if not isinstance(c, dict):
            continue
        total += 1
        if c.get("type") == "determinism_repro":
            if bool(c.get("match", False)):
                ok += 1
            continue
        if "match" in c:
            if bool(c.get("match", False)):
                ok += 1
            continue
        if "present" in c:
            if bool(c.get("present", False)):
                ok += 1
    return ok, total


def _render_row(row: dict[str, Any]) -> list[str]:
    case_id = str(row.get("id") or "")
    question = str(row.get("question") or "").strip()
    summary = str(row.get("summary") or "").strip() or "(no summary)"
    bullets = [str(b).strip() for b in (row.get("bullets") or []) if str(b).strip()]
    answer_bullets = [b for b in bullets if not b.lower().startswith("source:")][:2]
    expected_eval = row.get("expected_eval") if isinstance(row.get("expected_eval"), dict) else {}
    passed = bool(expected_eval.get("passed", False))
    checks = expected_eval.get("checks") if isinstance(expected_eval.get("checks"), list) else []
    checks_ok, checks_total = _check_score([c for c in checks if isinstance(c, dict)])
    providers = row.get("providers") if isinstance(row.get("providers"), list) else []
    providers_sorted = sorted(
        [p for p in providers if isinstance(p, dict)],
        key=lambda p: int(p.get("contribution_bp") or 0),
        reverse=True,
    )
    top = providers_sorted[:3]
    top_txt = ", ".join(
        f"{str(p.get('provider_id') or '?')}:{int(p.get('contribution_bp') or 0)}bp"
        for p in top
    ) or "none"

    out = [
        f"[{case_id}] pass={passed} checks={checks_ok}/{checks_total}",
        f"Q: {question}",
        f"A: {summary}",
    ]
    if answer_bullets:
        out.append("A_detail: " + " | ".join(answer_bullets))
    out.append(f"Proof: top_providers={top_txt}")
    out.append("")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="", help="Path to advanced20 JSON (defaults to latest).")
    parser.add_argument(
        "--output",
        default="docs/reports/advanced20_answers_latest.txt",
        help="Output text report path.",
    )
    args = parser.parse_args()

    src = Path(str(args.input).strip()) if str(args.input).strip() else _latest_advanced20()
    if not src.exists():
        print(json.dumps({"ok": False, "error": "advanced20_not_found", "input": str(src)}))
        return 2
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = [r for r in (data.get("rows") or []) if isinstance(r, dict)]
    lines: list[str] = []
    lines.append(f"source: {src}")
    lines.append(
        "evaluated_total="
        + str(data.get("evaluated_total"))
        + " passed="
        + str(data.get("evaluated_passed"))
        + " failed="
        + str(data.get("evaluated_failed"))
    )
    lines.append("")
    for row in rows:
        lines.extend(_render_row(row))
    rendered = "\n".join(lines).rstrip() + "\n"

    out = Path(str(args.output))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

