"""Gate: contract lockfile pins must match current contract files.

This is a cheap, deterministic integrity check that prevents silent drift
between schema/docs used by plugins and the recorded lock hash in
`contracts/lock.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    lock_path = REPO_ROOT / "contracts" / "lock.json"
    if not lock_path.exists():
        print("FAIL: contracts/lock.json missing")
        return 2
    payload = _load_json(lock_path)
    files = payload.get("files", {})
    if not isinstance(files, dict) or not files:
        print("FAIL: contracts/lock.json missing files map")
        return 2
    mismatches = []
    missing = []
    for rel, expected in sorted(files.items(), key=lambda item: item[0]):
        path = REPO_ROOT / str(rel)
        if not path.exists():
            missing.append(str(rel))
            continue
        actual = sha256_file(path)
        if str(actual) != str(expected):
            mismatches.append((str(rel), str(expected), str(actual)))
    if missing:
        for rel in missing[:80]:
            print(f"missing: {rel}")
    if mismatches:
        for rel, exp, act in mismatches[:80]:
            print(f"mismatch: {rel}: expected={exp} actual={act}")
    if missing or mismatches:
        print(f"FAIL: contract pins (missing={len(missing)} mismatches={len(mismatches)})")
        return 1
    print("OK: contract pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

