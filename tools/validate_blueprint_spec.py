"""Deterministic validator for blueprint spec checklist constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RE_TOP = re.compile(r"^#\s+(.+?)\s*$")
RE_SRC = re.compile(r"\bSRC-\d+\b")
RE_MOD = re.compile(r"^\s*[-•]\s*(MOD-\d+)\b")
RE_ADR = re.compile(r"^\s*[-•]\s*(ADR-\d+)\b")
RE_FS = re.compile(r"^\s*[-•]\s*(FS-\d+)\b")

REQUIRED_SECTIONS = [
    "1. Source_Index",
    "2. Coverage_Map",
    "3. Modules",
    "4. ADRs",
]


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def _section_ranges(lines: list[str]) -> list[tuple[str, int, int]]:
    headers: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        match = RE_TOP.match(line)
        if match:
            headers.append((match.group(1), idx))
    ranges: list[tuple[str, int, int]] = []
    for i, (title, start) in enumerate(headers):
        end = headers[i + 1][1] if i + 1 < len(headers) else len(lines)
        ranges.append((title, start + 1, end))
    return ranges


def _find_blocks(lines: list[str], matcher: re.Pattern[str], section_end: int) -> list[tuple[str, int, int]]:
    blocks: list[tuple[str, int, int]] = []
    idx = 0
    while idx < section_end:
        line = lines[idx]
        match = matcher.match(line)
        if match:
            block_id = match.group(1)
            start = idx
            idx += 1
            while idx < section_end:
                if RE_TOP.match(lines[idx]):
                    break
                if RE_MOD.match(lines[idx]) or RE_ADR.match(lines[idx]) or RE_FS.match(lines[idx]):
                    break
                idx += 1
            blocks.append((block_id, start, idx))
            continue
        idx += 1
    return blocks


def _extract_src_ids(lines: Iterable[str]) -> list[str]:
    src_ids: list[str] = []
    for line in lines:
        if line.lstrip().startswith(('-', '•')):
            src_ids.extend(RE_SRC.findall(line))
    return src_ids


def _duplicates(items: list[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for item in items:
        if item in seen:
            dupes.add(item)
        seen.add(item)
    return dupes


def validate_spec(path: Path, project_root: Path) -> ValidationResult:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Source_Document check
    source_line = next((line for line in lines if line.startswith("Source_Document:")), None)
    try:
        expected_rel = path.relative_to(project_root).as_posix()
    except ValueError:
        expected_rel = path.as_posix()
    if not source_line:
        errors.append("source_document_missing")
    else:
        value = source_line.split(":", 1)[1].strip()
        if not value:
            errors.append("source_document_empty")
        elif value != expected_rel:
            errors.append("source_document_mismatch")

    # Section structure
    ranges = _section_ranges(lines)
    titles = [title for title, _start, _end in ranges]
    if titles != REQUIRED_SECTIONS:
        errors.append("sections_mismatch")

    section_map = {title: (start, end) for title, start, end in ranges}

    # Source_Index + Coverage_Map
    src_index_ids: list[str] = []
    coverage_ids: list[str] = []
    if "1. Source_Index" in section_map:
        start, end = section_map["1. Source_Index"]
        src_index_ids = _extract_src_ids(lines[start:end])
    if "2. Coverage_Map" in section_map:
        start, end = section_map["2. Coverage_Map"]
        coverage_ids = _extract_src_ids(lines[start:end])

    if _duplicates(src_index_ids):
        errors.append("source_index_duplicates")
    if _duplicates(coverage_ids):
        errors.append("coverage_map_duplicates")

    src_index_set = set(src_index_ids)
    coverage_set = set(coverage_ids)
    if src_index_set != coverage_set:
        errors.append("src_sets_mismatch")

    referenced_srcs = set(RE_SRC.findall(text))
    if src_index_set != referenced_srcs:
        errors.append("dangling_src_refs")

    # MOD + ADR sources, FS tables
    modules_range = section_map.get("3. Modules")
    if modules_range:
        mod_blocks = _find_blocks(lines, RE_MOD, modules_range[1])
        fs_blocks = _find_blocks(lines, RE_FS, modules_range[1])
        for block_id, start, end in mod_blocks:
            if not any("Sources:" in line for line in lines[start:end]):
                errors.append(f"mod_missing_sources:{block_id}")
        for block_id, start, end in fs_blocks:
            if not any("Sources:" in line for line in lines[start:end]):
                errors.append(f"fs_missing_sources:{block_id}")
            table_start = None
            for idx in range(start, end):
                if "Sample_Table" in lines[idx]:
                    table_start = idx + 1
                    break
            if table_start is None:
                errors.append(f"fs_missing_table:{block_id}")
                continue
            row_count = 0
            for line in lines[table_start:end]:
                if not line.strip():
                    break
                if "|" in line:
                    row_count += 1
            if row_count < 4:
                errors.append(f"fs_table_too_small:{block_id}")

    adrs_range = section_map.get("4. ADRs")
    if adrs_range:
        adr_blocks = _find_blocks(lines, RE_ADR, adrs_range[1])
        for block_id, start, end in adr_blocks:
            if not any("Sources:" in line for line in lines[start:end]):
                errors.append(f"adr_missing_sources:{block_id}")

    return ValidationResult(ok=not errors, errors=errors)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("spec_path")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    spec_path = Path(args.spec_path).resolve()
    result = validate_spec(spec_path, project_root)
    if result.ok:
        return 0
    print("spec_validation_failed:" + ",".join(result.errors))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
