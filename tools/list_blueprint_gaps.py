"""List blueprint items that are not marked implemented in the gap tracker report."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


RE_GAP_NAME = re.compile(r"^blueprint-gap-(\d{4}-\d{2}-\d{2})\.md$")


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap", default="", help="Optional explicit gap report path.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    gap_path = (repo_root / args.gap).resolve() if args.gap else _latest_gap_report(repo_root / "docs" / "reports")
    lines = gap_path.read_text(encoding="utf-8").splitlines()

    items = []
    for raw in lines:
        line = raw.strip()
        if not line.startswith("| I"):
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        item_id, phase, title, status, _evidence = parts[:5]
        if item_id == "ID":
            continue
        items.append((item_id, phase, title, status))

    not_ok = [it for it in items if it[3] != "implemented"]
    print(f"gap_report={gap_path.relative_to(repo_root)} total={len(items)} not_implemented={len(not_ok)}")
    for item_id, phase, title, status in not_ok:
        print(f"{item_id}\t{status}\t{phase}\t{title}")
    return 0 if not_ok else 0


if __name__ == "__main__":
    raise SystemExit(main())

