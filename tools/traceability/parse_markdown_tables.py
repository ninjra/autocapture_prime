"""Minimal deterministic markdown table parser for repo reports.

We intentionally keep this simple and stable:
- Only supports the '|' pipe tables used in docs/reports/*.md.
- No attempt to support escaped pipes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableRow:
    raw: str
    cols: list[str]


def iter_pipe_table_rows(lines: list[str], *, prefix: str) -> list[TableRow]:
    rows: list[TableRow] = []
    for raw in lines:
        if not raw.startswith(prefix):
            continue
        # Strip leading/trailing pipe, then split.
        parts = [c.strip() for c in raw.strip().strip("|").split("|")]
        rows.append(TableRow(raw=raw, cols=parts))
    return rows

