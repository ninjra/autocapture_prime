"""Integrity gate for frozen surfaces + contract pins."""

from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file
from tools import frozen_surfaces


def _contracts_ok() -> tuple[bool, list[dict[str, str]]]:
    lock_path = Path("contracts/lock.json")
    if not lock_path.exists():
        return False, [{"path": "contracts/lock.json", "error": "missing"}]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    mismatches = []
    for rel, expected in lock.get("files", {}).items():
        actual = sha256_file(rel)
        if actual != expected:
            mismatches.append({"path": rel, "expected": expected, "actual": actual})
    return len(mismatches) == 0, mismatches


def run() -> dict:
    current = frozen_surfaces.compute_surfaces()
    baseline = frozen_surfaces._load_baseline()
    report = frozen_surfaces.compare_surfaces(baseline, current)
    contracts_ok, mismatches = _contracts_ok()
    ok = bool(report.get("ok")) and contracts_ok
    return {
        "ok": ok,
        "frozen_surfaces": report,
        "contracts_ok": contracts_ok,
        "contract_mismatches": mismatches,
    }
