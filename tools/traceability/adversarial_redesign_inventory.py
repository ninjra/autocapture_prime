"""Parse adversarial redesign recommendations from the redesign doc.

This module supports:
- Inventory: enumerate all recommendation IDs + titles from markdown headings.
- Field extraction: parse the per-recommendation table and pull out key fields
  (notably enforcement_location + regression_detection) used by traceability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RE_ID_HEADING = re.compile(r"^###\s+([A-Z]{2,6}-\d{2})\b")
RE_TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")


@dataclass(frozen=True)
class RedesignItem:
    item_id: str
    title: str


@dataclass(frozen=True)
class RedesignItemFields:
    item_id: str
    title: str
    fields: dict[str, str]

    def field(self, name: str) -> str:
        return str(self.fields.get(name, "") or "").strip()


def iter_redesign_items(doc_path: Path) -> list[RedesignItem]:
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    ids: list[tuple[str, int]] = []
    for idx, raw in enumerate(lines):
        m = RE_ID_HEADING.match(raw.strip())
        if not m:
            continue
        ids.append((m.group(1), idx))
    items: list[RedesignItem] = []
    for i, (item_id, start_idx) in enumerate(ids):
        end_idx = ids[i + 1][1] if i + 1 < len(ids) else len(lines)
        section = lines[start_idx:end_idx]
        title = ""
        # Heuristic: first "| Recommendation |" row's payload, else first non-empty paragraph line.
        for raw in section:
            line = raw.strip()
            if line.startswith("| Recommendation |"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) >= 2:
                    title = parts[1].strip()
                break
        if not title:
            for raw in section[1:]:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("|") or line.startswith("**") or line.startswith("- "):
                    continue
                title = line
                break
        title = (title or "").strip()
        items.append(RedesignItem(item_id=item_id, title=title))
    # Stable unique by ID.
    seen: set[str] = set()
    out: list[RedesignItem] = []
    for item in items:
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        out.append(item)
    out.sort(key=lambda it: it.item_id)
    return out


def parse_redesign_doc(doc_path: Path) -> list[RedesignItemFields]:
    """Parse per-item field tables from the redesign doc.

    The doc format uses a markdown heading per item:
      ### FND-01
    Followed by a 2-col table:
      | Field | Value |
      | --- | --- |
      | enforcement_location | pathA, pathB |
      | regression_detection | tests/x.py; tools/y.py (add check); ... |
    """

    lines = doc_path.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[str, int]] = []
    for idx, raw in enumerate(lines):
        m = RE_ID_HEADING.match(raw.strip())
        if m:
            headings.append((m.group(1), idx))

    out: list[RedesignItemFields] = []
    for i, (item_id, start_idx) in enumerate(headings):
        end_idx = headings[i + 1][1] if i + 1 < len(headings) else len(lines)
        section = lines[start_idx:end_idx]

        # Title heuristic mirrors iter_redesign_items().
        title = ""
        for raw in section:
            line = raw.strip()
            if line.startswith("| Recommendation |"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) >= 2:
                    title = parts[1].strip()
                break
        if not title:
            for raw in section[1:]:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("|") or line.startswith("**") or line.startswith("- "):
                    continue
                title = line
                break
        title = (title or "").strip()

        fields: dict[str, str] = {}
        in_table = False
        for raw in section:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("| Field | Value |"):
                in_table = True
                continue
            if not in_table:
                continue
            # Skip separator row.
            if line.startswith("| ---"):
                continue
            m = RE_TABLE_ROW.match(line)
            if not m:
                # Stop at the first non-row once table started.
                if in_table and line and not line.startswith("|"):
                    break
                continue
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key and val:
                fields[key] = val

        out.append(RedesignItemFields(item_id=item_id, title=title, fields=fields))

    # Stable unique by ID.
    seen: set[str] = set()
    uniq: list[RedesignItemFields] = []
    for item in out:
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        uniq.append(item)
    uniq.sort(key=lambda it: it.item_id)
    return uniq


def split_enforcement_locations(value: str) -> list[str]:
    raw = str(value or "")
    parts = [p.strip() for p in raw.split(",")]
    cleaned: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        # The redesign doc may annotate paths with parentheses, e.g. "foo.py (new)".
        # Treat the first whitespace-delimited token as the actual path/glob.
        token = item.split()[0].strip()
        token = token.rstrip(".")
        if token:
            cleaned.append(token)
    # Stable de-dup.
    seen: set[str] = set()
    out: list[str] = []
    for entry in cleaned:
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out


_REGRESS_SPLIT_RE = re.compile(r";|,")


def split_regression_validators(value: str) -> tuple[list[str], list[str]]:
    """Return (paths, needs_work) for regression_detection field.

    needs_work carries entries that explicitly say "(add ...)" / "(extend ...)" etc,
    which are not yet verifiable by existence alone.
    """

    raw = str(value or "")
    paths: list[str] = []
    needs_work: list[str] = []
    for chunk in _REGRESS_SPLIT_RE.split(raw):
        item = chunk.strip()
        if not item:
            continue
        if "ANY_REGRESS" in item:
            continue
        # Capture a leading repo-relative path token when present.
        token = item.split()[0].strip()
        if "/" in token or token.endswith((".py", ".sh", ".ps1", ".md")):
            token = token.strip().rstrip(".")
        else:
            token = ""
        if "(" in item and ")" in item:
            inner = item[item.find("(") + 1 : item.rfind(")")].strip().lower()
            if any(word in inner for word in ("add ", "extend", "update", "wire", "integrate")):
                if token:
                    needs_work.append(token)
                else:
                    needs_work.append(item)
                continue
        if token:
            paths.append(token)
    # De-dup stable.
    def _uniq(seq: list[str]) -> list[str]:
        seen2: set[str] = set()
        out2: list[str] = []
        for x in seq:
            if x in seen2:
                continue
            seen2.add(x)
            out2.append(x)
        return out2

    return _uniq(paths), _uniq(needs_work)


def _glob_any(repo_root: Path, pattern: str) -> bool:
    pat = str(pattern).strip()
    if not pat:
        return False
    # Treat bare directories as existing evidence too.
    candidate = repo_root / pat
    if "*" not in pat and "?" not in pat and "[" not in pat:
        return candidate.exists()
    matches = list(repo_root.glob(pat))
    return bool(matches)


def compute_status(
    *,
    repo_root: Path,
    evidence: list[str],
    validators: list[str],
    needs_work: list[str] | None = None,
) -> str:
    needs_work = list(needs_work or [])
    if needs_work:
        # Explicitly flagged in the redesign doc as "add/extend" work.
        return "partial"
    if evidence and not all(_glob_any(repo_root, ev) for ev in evidence):
        return "missing"
    if validators and not all(_glob_any(repo_root, v) for v in validators):
        return "partial"
    if evidence or validators:
        return "implemented"
    return "missing"
