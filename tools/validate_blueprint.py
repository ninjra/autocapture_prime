"""Validator for BLUEPRINT.md checklist constraints."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TOP_LEVEL_HEADINGS = [
    "1. System Context & Constraints",
    "2. Functional Modules & Logic",
    "3. Architecture Decision Records (ADRs)",
    "4. Grounding Data (Few-Shot Samples)",
]

RE_TOP = re.compile(r"^#\s+(.+?)\s*$")
RE_OBJ = re.compile(r"^\s*\*?\s*Object_ID:\s*(MOD-\d+)\b")
RE_ADR = re.compile(r"^\s*\*?\s*ADR_ID:\s*(ADR-\d+)\b")
RE_SAMPLE = re.compile(r"^\s*\*?\s*Sample_ID:\s*(SAMPLE-\d+)\b")
RE_SRC = re.compile(r"\bSRC-\d+\b")
RE_DEFERRAL = re.compile(r"\b(TODO|TBD|later|future work|implement later)\b", re.IGNORECASE)
RE_I_ITEM = re.compile(r"\bI\d{3}\b")

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key_block": re.compile(r"-----BEGIN"),
    "sk_token": re.compile(r"sk-[A-Za-z0-9]{20,}"),
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def _code_fence_mask(lines: list[str]) -> list[bool]:
    mask: list[bool] = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            mask.append(True)
            in_fence = not in_fence
            continue
        mask.append(in_fence)
    return mask


def _section_ranges(lines: list[str], fence_mask: list[bool]) -> list[tuple[str, int, int]]:
    headers: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        if fence_mask[idx]:
            continue
        match = RE_TOP.match(line)
        if match:
            headers.append((match.group(1), idx))
    ranges: list[tuple[str, int, int]] = []
    for i, (title, start) in enumerate(headers):
        end = headers[i + 1][1] if i + 1 < len(headers) else len(lines)
        ranges.append((title, start + 1, end))
    return ranges


def _find_marker(lines: list[str], start: int, end: int, name: str) -> int | None:
    marker_names = {
        name,
        f"{name}:",
        f"## {name}",
        f"## {name}:",
    }
    for idx in range(start, end):
        if lines[idx].strip() in marker_names:
            return idx
    return None


def _extract_src_ids(lines: Iterable[str]) -> list[str]:
    src_ids: list[str] = []
    for line in lines:
        src_ids.extend(RE_SRC.findall(line))
    return src_ids


def _extract_i_ids(lines: Iterable[str]) -> list[str]:
    ids: list[str] = []
    for line in lines:
        ids.extend(RE_I_ITEM.findall(line))
    return ids


def _duplicates(items: list[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for item in items:
        if item in seen:
            dupes.add(item)
        seen.add(item)
    return dupes


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "…"
    return value[:4] + "…" + value[-4:]


def validate_blueprint(path: Path) -> ValidationResult:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    fence_mask = _code_fence_mask(lines)

    # Top-level headings
    headings = []
    for idx, line in enumerate(lines):
        if fence_mask[idx]:
            continue
        match = RE_TOP.match(line)
        if match:
            headings.append(match.group(1))
    if headings != TOP_LEVEL_HEADINGS:
        errors.append(
            "top_level_headings_mismatch: expected="
            + ", ".join(TOP_LEVEL_HEADINGS)
            + "; found="
            + ", ".join(headings)
        )

    # Deferral markers outside code fences and blockquotes
    for idx, line in enumerate(lines):
        if fence_mask[idx]:
            continue
        if line.lstrip().startswith(">"):
            continue
        match = RE_DEFERRAL.search(line)
        if match:
            token = match.group(0)
            errors.append(f"deferral_marker:{token}:line:{idx + 1}")

    # Secret scan
    for idx, line in enumerate(lines):
        for label, pattern in SECRET_PATTERNS.items():
            match = pattern.search(line)
            if match:
                snippet = _redact(match.group(0))
                errors.append(f"secret_pattern:{label}:line:{idx + 1}:value:{snippet}")

    # Section ranges
    ranges = _section_ranges(lines, fence_mask)
    section_map = {title: (start, end) for title, start, end in ranges}

    # Source_Index / Coverage_Map integrity
    sec1 = section_map.get(TOP_LEVEL_HEADINGS[0])
    if not sec1:
        errors.append("section_missing:1")
    else:
        s_start, s_end = sec1
        src_marker = _find_marker(lines, s_start, s_end, "Source_Index")
        cov_marker = _find_marker(lines, s_start, s_end, "Coverage_Map")
        val_marker = _find_marker(lines, s_start, s_end, "Validation_Checklist")
        legacy_marker = _find_marker(lines, s_start, s_end, "Legacy_I_Item_Crosswalk")
        if src_marker is None:
            errors.append("source_index_missing")
        if cov_marker is None:
            errors.append("coverage_map_missing")
        if val_marker is None:
            errors.append("validation_checklist_missing")
        if legacy_marker is None:
            errors.append("legacy_i_item_crosswalk_missing")
        if src_marker is not None and cov_marker is not None:
            src_ids = _extract_src_ids(lines[src_marker + 1:cov_marker])
            coverage_end = val_marker if val_marker is not None else s_end
            cov_ids = _extract_src_ids(lines[cov_marker + 1:coverage_end])
            dupes = _duplicates(src_ids)
            if dupes:
                errors.append("source_index_duplicates:" + ",".join(sorted(dupes)))
            cov_counts = {src: cov_ids.count(src) for src in set(cov_ids)}
            cov_bad = [src for src, count in cov_counts.items() if count != 1]
            if cov_bad:
                errors.append("coverage_map_non_unique:" + ",".join(sorted(cov_bad)))
            src_set = set(src_ids)
            cov_set = set(cov_ids)
            missing = sorted(src_set - cov_set)
            extra = sorted(cov_set - src_set)
            if missing:
                errors.append("coverage_map_missing_src:" + ",".join(missing))
            if extra:
                errors.append("coverage_map_extra_src:" + ",".join(extra))

        if legacy_marker is not None:
            crosswalk_end = s_end
            if s_end > legacy_marker:
                crosswalk_end = s_end
            crosswalk_lines = lines[legacy_marker + 1:crosswalk_end]
            # Rows look like Markdown table lines starting with | I###
            row_lines = [line for line in crosswalk_lines if line.strip().startswith("| I")]
            i_ids = []
            for row in row_lines:
                parts = [p.strip() for p in row.strip().split("|")[1:-1]]
                if len(parts) < 6:
                    errors.append("legacy_i_item_row_malformed")
                    continue
                i_id, _phase, _title, mod_cov, _adr_cov, test_gate = parts[:6]
                if i_id == "I-ID":
                    continue
                if not RE_I_ITEM.fullmatch(i_id):
                    errors.append(f"legacy_i_item_id_invalid:{i_id}")
                    continue
                if not mod_cov or mod_cov == "-":
                    errors.append(f"legacy_i_item_mod_missing:{i_id}")
                if not test_gate or test_gate == "-":
                    errors.append(f"legacy_i_item_test_missing:{i_id}")
                i_ids.append(i_id)

            dupes = _duplicates(i_ids)
            if dupes:
                errors.append("legacy_i_item_duplicates:" + ",".join(sorted(dupes)))

            # Cross-check against legacy implementation matrix if present
            legacy_path = Path("docs/reports/implementation_matrix.md")
            if legacy_path.exists():
                legacy_lines = legacy_path.read_text(encoding="utf-8").splitlines()
                legacy_ids = []
                for line in legacy_lines:
                    if line.startswith("| I"):
                        parts = [p.strip() for p in line.strip().split("|")[1:-1]]
                        if parts:
                            if parts[0] == "ItemID":
                                continue
                            legacy_ids.append(parts[0])
                legacy_set = set(legacy_ids)
                i_set = set(i_ids)
                missing = sorted(legacy_set - i_set)
                extra = sorted(i_set - legacy_set)
                if missing:
                    errors.append("legacy_i_item_missing:" + ",".join(missing))
                if extra:
                    errors.append("legacy_i_item_extra:" + ",".join(extra))
            else:
                errors.append("legacy_i_item_source_missing:docs/reports/implementation_matrix.md")

    # Section 2: MOD blocks + business logic modules
    sec2 = section_map.get(TOP_LEVEL_HEADINGS[1])
    business_logic: list[str] = []
    if sec2:
        start, end = sec2
        obj_indices: list[tuple[str, int]] = []
        for idx in range(start, end):
            match = RE_OBJ.match(lines[idx])
            if match:
                obj_indices.append((match.group(1), idx))
        for i, (mod_id, idx) in enumerate(obj_indices):
            block_end = obj_indices[i + 1][1] if i + 1 < len(obj_indices) else end
            block = lines[idx:block_end]
            sources_count = sum(1 for line in block if "Sources:" in line)
            iface_count = sum(1 for line in block if "Interface_Definition:" in line)
            if sources_count != 1:
                errors.append(f"mod_sources_count:{mod_id}:{sources_count}")
            if iface_count != 1:
                errors.append(f"mod_interface_count:{mod_id}:{iface_count}")
            for line in block:
                if line.strip().startswith("Object_Type:") and "Business Logic" in line:
                    business_logic.append(mod_id)
                    break
    else:
        errors.append("section_missing:2")

    # Section 3: ADR blocks
    sec3 = section_map.get(TOP_LEVEL_HEADINGS[2])
    if sec3:
        start, end = sec3
        adr_indices: list[tuple[str, int]] = []
        for idx in range(start, end):
            match = RE_ADR.match(lines[idx])
            if match:
                adr_indices.append((match.group(1), idx))
        for i, (adr_id, idx) in enumerate(adr_indices):
            block_end = adr_indices[i + 1][1] if i + 1 < len(adr_indices) else end
            block = lines[idx:block_end]
            if not any("Sources:" in line for line in block):
                errors.append(f"adr_missing_sources:{adr_id}")
    else:
        errors.append("section_missing:3")

    # Section 4: samples
    sec4 = section_map.get(TOP_LEVEL_HEADINGS[3])
    samples_for_module: dict[str, int] = {}
    if sec4:
        start, end = sec4
        sample_indices: list[tuple[str, int]] = []
        for idx in range(start, end):
            match = RE_SAMPLE.match(lines[idx])
            if match:
                sample_indices.append((match.group(1), idx))
        for i, (sample_id, idx) in enumerate(sample_indices):
            block_end = sample_indices[i + 1][1] if i + 1 < len(sample_indices) else end
            block = lines[idx:block_end]
            module = None
            for line in block:
                if line.strip().startswith("Module:"):
                    module = line.split(":", 1)[1].strip()
                    break
            if not module:
                errors.append(f"sample_missing_module:{sample_id}")
                continue
            fence_start = None
            fence_end = None
            for j, line in enumerate(block):
                if line.strip().startswith("```"):
                    fence_start = j + 1
                    for k in range(j + 1, len(block)):
                        if block[k].strip().startswith("```"):
                            fence_end = k
                            break
                    break
            if fence_start is None or fence_end is None:
                errors.append(f"sample_missing_table:{sample_id}")
                continue
            table_lines = block[fence_start:fence_end]
            rows = [line for line in table_lines if "|" in line]
            if rows:
                # remove separator rows
                data_rows = [line for line in rows if not re.match(r"^\s*\|\s*-{2,}", line)]
                if len(data_rows) > 0:
                    data_count = max(0, len(data_rows) - 1)
                else:
                    data_count = 0
            else:
                data_count = 0
            samples_for_module[module] = max(samples_for_module.get(module, 0), data_count)

        for mod_id in business_logic:
            count = samples_for_module.get(mod_id, 0)
            if count < 3:
                errors.append(f"sample_rows_insufficient:{mod_id}:{count}")
    else:
        errors.append("section_missing:4")

    return ValidationResult(ok=not errors, errors=errors)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="BLUEPRINT.md")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"blueprint_missing:{path}")
        return 1

    result = validate_blueprint(path)
    if result.ok:
        return 0
    print("Blueprint validation failed:")
    for idx, err in enumerate(result.errors, start=1):
        print(f"{idx}. {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
