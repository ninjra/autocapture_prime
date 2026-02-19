#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _docs_matrix_rows(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| `docs/"))


def _docs_file_count() -> int:
    return sum(
        1
        for p in (REPO_ROOT / "docs").rglob("*")
        if p.is_file() and p.suffix.lower() in {".md", ".txt"}
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh and verify implementation matrices.")
    parser.add_argument("--allow-misses", action="store_true", help="Do not fail on miss rows > 0.")
    args = parser.parse_args()

    py = "python3"
    _run([py, "tools/full_repo_miss_inventory.py"])
    _run([py, "tools/generate_full_remaining_matrix.py"])
    _run([py, "tools/generate_docs_md_txt_status_matrix.py"])

    inv = _load_json(REPO_ROOT / "artifacts/repo_miss_inventory/latest.json")
    miss_rows = int((inv.get("summary") or {}).get("rows_total", 0))
    gate_failures = int((inv.get("summary") or {}).get("gate_failures_total", 0))

    docs_total = _docs_file_count()
    docs_rows = _docs_matrix_rows(REPO_ROOT / "docs/reports/docs_md_txt_status_matrix.md")
    docs_matrix_ok = docs_total == docs_rows

    out = {
        "ok": bool((args.allow_misses or miss_rows == 0) and docs_matrix_ok),
        "miss_rows_total": miss_rows,
        "gate_failures_total": gate_failures,
        "docs_md_txt_count": docs_total,
        "docs_matrix_rows": docs_rows,
        "docs_matrix_row_match": docs_matrix_ok,
        "allow_misses": bool(args.allow_misses),
        "artifacts": {
            "miss_inventory_json": "artifacts/repo_miss_inventory/latest.json",
            "remaining_matrix_md": "docs/reports/implementation_matrix_remaining_2026-02-12.md",
            "docs_status_matrix_md": "docs/reports/docs_md_txt_status_matrix.md",
        },
    }
    print(json.dumps(out, indent=2, sort_keys=True))

    if not out["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
