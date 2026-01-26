"""Patch helpers for prompts."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Iterable


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def create_patch(original: str, updated: str, *, fromfile: str = "a/prompt.txt", tofile: str = "b/prompt.txt") -> str:
    original = _ensure_trailing_newline(original)
    updated = _ensure_trailing_newline(updated)
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
    )
    return "".join(diff)


def apply_patch_to_text(original: str, patch_text: str) -> str:
    if not patch_text.strip():
        return original
    lines = patch_text.splitlines(keepends=True)
    original = _ensure_trailing_newline(original)
    out: list[str] = []
    idx = 0
    orig_lines = original.splitlines(keepends=True)
    orig_idx = 0
    hunk_re = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("---") or line.startswith("+++"):
            idx += 1
            continue
        if line.startswith("@@"):
            match = hunk_re.match(line)
            if not match:
                idx += 1
                continue
            start_old = int(match.group(1)) - 1
            out.extend(orig_lines[orig_idx:start_old])
            orig_idx = start_old
            idx += 1
            while idx < len(lines) and not lines[idx].startswith("@@"):
                hline = lines[idx]
                if hline.startswith(" "):
                    out.append(orig_lines[orig_idx])
                    orig_idx += 1
                elif hline.startswith("-"):
                    orig_idx += 1
                elif hline.startswith("+"):
                    out.append(hline[1:])
                idx += 1
            continue
        idx += 1

    out.extend(orig_lines[orig_idx:])
    return "".join(out)


def apply_patch_file(path: str | Path, patch_text: str) -> str:
    path = Path(path)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = apply_patch_to_text(original, patch_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return updated
