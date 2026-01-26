"""Verify dependency lock matches pyproject.toml."""

from __future__ import annotations

import json
from pathlib import Path

from tools.generate_dep_lock import LOCK_PATH, build_lock


def main() -> int:
    if not LOCK_PATH.exists():
        print(f"FAIL: missing {LOCK_PATH}")
        return 1
    expected = build_lock()
    actual = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    mismatches = []
    for key in ("version", "python", "dependencies", "optional_dependencies", "content_hash"):
        if actual.get(key) != expected.get(key):
            mismatches.append(key)
    if mismatches:
        print(f"FAIL: lock mismatch for {', '.join(mismatches)}")
        return 1
    print("OK: dependency lock matches pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
