"""Windows path normalization helpers (SEC-01).

These helpers are safe to import on non-Windows hosts. They use `ntpath` so we
can unit test Windows path semantics from WSL/Linux CI.
"""

from __future__ import annotations

import ntpath


def normalize_windows_path_str(path: str) -> str:
    p = str(path or "")
    if not p:
        return ""
    # Normalize separators first.
    p = p.replace("/", "\\")
    # Strip Win32 namespace prefixes so comparisons are consistent.
    for prefix in ("\\\\?\\", "\\\\.\\" ):
        if p.startswith(prefix):
            p = p[len(prefix) :]
            break
    # Collapse ., .., duplicate separators, etc.
    p = ntpath.normpath(p)
    # Case-insensitive filesystem semantics.
    p = ntpath.normcase(p)
    return p


def windows_is_within(root: str, candidate: str) -> bool:
    r = normalize_windows_path_str(root)
    c = normalize_windows_path_str(candidate)
    if not r or not c:
        return False
    try:
        common = ntpath.commonpath([r, c])
    except Exception:
        return False
    return common == r

