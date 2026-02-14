#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = REPO_ROOT / "contracts" / "chronicle" / "v0" / "contract_pins.json"


def _compute_files() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted((REPO_ROOT / "contracts" / "chronicle" / "v0").glob("*")):
        if path.is_file() and path.name != "contract_pins.json":
            rel = path.relative_to(REPO_ROOT).as_posix()
            out[rel] = sha256_file(path)
    return out


def main() -> int:
    actual = _compute_files()
    if not PIN_PATH.exists():
        print("FAIL: contracts/chronicle/v0/contract_pins.json missing")
        return 2
    expected = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    files = expected.get("files", {})
    if not isinstance(files, dict):
        print("FAIL: invalid chronicle contract pins format")
        return 2
    mismatches = []
    for rel, digest in actual.items():
        if files.get(rel) != digest:
            mismatches.append((rel, files.get(rel), digest))
    missing = [rel for rel in files.keys() if rel not in actual]
    if missing or mismatches:
        for rel in missing:
            print(f"missing: {rel}")
        for rel, exp, got in mismatches:
            print(f"mismatch: {rel} expected={exp} actual={got}")
        print("FAIL: chronicle contract drift")
        return 1
    print("OK: chronicle contracts pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
