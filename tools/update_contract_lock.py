#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    contracts = root / "contracts"
    files: dict[str, str] = {}
    for path in sorted(contracts.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if not rel.startswith("contracts/"):
            continue
        # The lock file must not include itself (self-referential hash).
        if rel == "contracts/lock.json":
            continue
        # Only hash contract artifacts (schemas + docs), not helper Python.
        if path.suffix.lower() not in {".json", ".md"}:
            continue
        files[rel] = sha256_file(root / rel)

    lock = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": {k: files[k] for k in sorted(files.keys())},
    }
    (contracts / "lock.json").write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
