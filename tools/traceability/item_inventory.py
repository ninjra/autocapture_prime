"""Inventory items in the implementation matrix and blueprint items list.

This is a low-resource helper used to verify coverage and to bootstrap more
structured traceability manifests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys

# Allow running as a standalone script from any CWD.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from tools.traceability.parse_markdown_tables import iter_pipe_table_rows  # noqa: E402


@dataclass(frozen=True)
class MatrixItem:
    item_id: str
    phase: str
    title: str
    status: str


def _load_matrix_items(repo_root: Path) -> list[MatrixItem]:
    path = repo_root / "docs" / "reports" / "implementation_matrix.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = iter_pipe_table_rows(lines, prefix="| ")
    items: list[MatrixItem] = []
    for row in rows:
        if not row.cols:
            continue
        if row.cols[0] in {"ItemID", "---"}:
            continue
        if not (row.cols[0].startswith("I") or row.cols[0].startswith("FX")):
            continue
        if len(row.cols) < 4:
            continue
        items.append(
            MatrixItem(
                item_id=row.cols[0],
                phase=row.cols[1],
                title=row.cols[2],
                status=row.cols[3],
            )
        )
    # De-dupe deterministically.
    seen: set[str] = set()
    out: list[MatrixItem] = []
    for it in items:
        if it.item_id in seen:
            continue
        seen.add(it.item_id)
        out.append(it)
    return sorted(out, key=lambda it: it.item_id)


def _load_blueprint_items(repo_root: Path) -> dict[str, dict]:
    path = repo_root / "tools" / "blueprint_items.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for it in items:
        by_id[str(it.get("id", "")).strip()] = it
    return by_id


def main() -> int:
    repo_root = _REPO_ROOT
    matrix = _load_matrix_items(repo_root)
    blueprint = _load_blueprint_items(repo_root)

    matrix_ids = [it.item_id for it in matrix]
    fx_ids = [i for i in matrix_ids if i.startswith("FX")]
    i_ids = [i for i in matrix_ids if i.startswith("I")]
    missing_in_blueprint = [i for i in i_ids if i not in blueprint]
    extra_in_blueprint = sorted([i for i in blueprint.keys() if i not in i_ids])

    print(f"matrix_total={len(matrix_ids)} fx={len(fx_ids)} i={len(i_ids)}")
    print(f"blueprint_items_total={len(blueprint)}")
    print(f"matrix_i_missing_in_blueprint={len(missing_in_blueprint)}")
    for i in missing_in_blueprint[:50]:
        print(f"missing_blueprint_item: {i}")
    print(f"blueprint_extra_not_in_matrix={len(extra_in_blueprint)}")
    for i in extra_in_blueprint[:50]:
        print(f"extra_blueprint_item: {i}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
