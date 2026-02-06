"""Update blueprint Coverage_Map from the latest blueprint gap tracker report.

This is intentionally lightweight and deterministic:
  - No repo-wide scanning (keeps WSL stable).
  - Uses the curated evidence references already audited in docs/reports/blueprint-gap-*.md.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


RE_GAP_NAME = re.compile(r"^blueprint-gap-(\d{4}-\d{2}-\d{2})\.md$")


@dataclass(frozen=True)
class GapRow:
    item_id: str  # I001
    phase: str
    title: str
    status: str
    evidence: list[str]


def _latest_gap_report(reports_dir: Path) -> Path:
    best = None
    best_date = ""
    for path in sorted(reports_dir.iterdir()):
        if not path.is_file():
            continue
        m = RE_GAP_NAME.match(path.name)
        if not m:
            continue
        date = m.group(1)
        if date > best_date:
            best_date = date
            best = path
    if best is None:
        raise SystemExit(f"No blueprint gap reports found in {reports_dir}")
    return best


def _parse_gap_table(md_path: Path) -> list[GapRow]:
    rows: list[GapRow] = []
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("| I"):
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        item_id, phase, title, status, evidence_raw = parts[:5]
        if item_id == "ID":
            continue
        evidence = [e.strip() for e in evidence_raw.split("<br>") if e.strip()]
        rows.append(GapRow(item_id=item_id, phase=phase, title=title, status=status, evidence=evidence))
    if not rows:
        raise SystemExit(f"No gap rows found in {md_path}")
    return rows


def _src_from_item_id(item_id: str) -> str:
    m = re.fullmatch(r"I(\d{3})", item_id.strip())
    if not m:
        raise ValueError(f"Unexpected item id: {item_id}")
    return f"SRC-{m.group(1)}"


def _render_coverage_lines(rows: list[GapRow]) -> list[str]:
    rendered: list[tuple[str, str]] = []
    for row in rows:
        src = _src_from_item_id(row.item_id)
        evidence = "; ".join(row.evidence) if row.evidence else "(no evidence listed)"
        rendered.append((src, f"- {src}: {row.status}; {evidence}"))
    rendered.sort(key=lambda t: t[0])
    return [line for _src, line in rendered]


def _replace_section(md_path: Path, *, header: str, next_header: str, new_lines: list[str]) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start_idx = i
            continue
        if start_idx is not None and line.strip() == next_header:
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise SystemExit(f"Could not locate section {header}..{next_header} in {md_path}")

    out = []
    out.extend(lines[: start_idx + 1])
    out.append("")  # blank line after header
    out.extend(new_lines)
    out.append("")  # blank line before next header
    out.extend(lines[end_idx:])
    md_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spec",
        default="docs/spec/autocapture_nx_blueprint_2026-01-24.md",
        help="Blueprint spec markdown path to update.",
    )
    parser.add_argument(
        "--gap",
        default="",
        help="Optional explicit gap report path; defaults to latest docs/reports/blueprint-gap-*.md.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    spec_path = (repo_root / args.spec).resolve()
    if not spec_path.exists():
        raise SystemExit(f"Spec not found: {spec_path}")

    if args.gap:
        gap_path = (repo_root / args.gap).resolve()
    else:
        gap_path = _latest_gap_report(repo_root / "docs" / "reports")
    if not gap_path.exists():
        raise SystemExit(f"Gap report not found: {gap_path}")

    rows = _parse_gap_table(gap_path)
    coverage = _render_coverage_lines(rows)
    _replace_section(spec_path, header="# 2. Coverage_Map", next_header="# 3. Modules", new_lines=coverage)
    print(f"OK: updated Coverage_Map from {gap_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

