"""Report adversarial redesign coverage gaps.

Writes a markdown report under docs/reports/ and prints a one-line summary.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    root = _repo_root()
    trace_path = root / "tools" / "traceability" / "adversarial_redesign_traceability.json"
    payload = _load_json(trace_path)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        raise SystemExit("invalid_traceability_shape")

    rows: list[dict[str, Any]] = [r for r in items if isinstance(r, dict)]
    rows.sort(key=lambda r: str(r.get("id", "")))
    counts = Counter(str(r.get("status", "")) for r in rows)

    report_dir = root / "docs" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"adversarial-redesign-gap-{_utc_date()}.md"

    def _fmt_list(values: list[str]) -> str:
        if not values:
            return ""
        return "<br>".join(str(v) for v in values)

    lines: list[str] = []
    lines.append("# Adversarial Redesign Coverage Gaps")
    lines.append("")
    lines.append(f"Generated: {_utc_date()}")
    lines.append("")
    lines.append(f"- total: {len(rows)}")
    lines.append(f"- implemented: {counts.get('implemented', 0)}")
    lines.append(f"- partial: {counts.get('partial', 0)}")
    lines.append(f"- missing: {counts.get('missing', 0)}")
    lines.append("")
    lines.append("| ID | Status | Title | Evidence | Validators |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in rows:
        rid = str(r.get("id", "")).strip()
        status = str(r.get("status", "")).strip()
        title = str(r.get("title", "")).strip().replace("\n", " ")
        ev = r.get("evidence", [])
        val = r.get("validators", [])
        ev_list = [str(x) for x in ev] if isinstance(ev, list) else []
        val_list = [str(x) for x in val] if isinstance(val, list) else []
        lines.append(f"| {rid} | {status} | {title} | {_fmt_list(ev_list)} | {_fmt_list(val_list)} |")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"gap_report={report_path.relative_to(root)} total={len(rows)} "
        f"implemented={counts.get('implemented',0)} partial={counts.get('partial',0)} missing={counts.get('missing',0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

