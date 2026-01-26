"""Provenance gate for schema + ledger integrity prerequisites."""

from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


def run() -> dict:
    issues: list[str] = []
    lock_path = Path("contracts/lock.json")
    if not lock_path.exists():
        issues.append("contracts_lock_missing")
        return {"ok": False, "issues": issues}
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    files = lock.get("files", {})
    for rel in ("contracts/ledger_schema.json", "contracts/journal_schema.json"):
        path = Path(rel)
        if not path.exists():
            issues.append(f"missing:{rel}")
            continue
        expected = files.get(rel)
        actual = sha256_file(rel)
        if expected != actual:
            issues.append(f"hash_mismatch:{rel}")
    return {"ok": len(issues) == 0, "issues": issues}
