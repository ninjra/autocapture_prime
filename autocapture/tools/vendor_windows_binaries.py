"""Vendor binary verifier (Windows)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any


EXPECTED_BINARIES = {
    "qdrant.exe": None,
    "ffmpeg.exe": None,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_binaries(root: str | Path = "vendor") -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": True, "skipped": True, "missing": [], "mismatched": []}
    root = Path(root)
    missing = []
    mismatched = []
    for name, expected in EXPECTED_BINARIES.items():
        path = root / name
        if not path.exists():
            missing.append(name)
            continue
        if expected:
            actual = _sha256(path)
            if actual != expected:
                mismatched.append({"name": name, "expected": expected, "actual": actual})
    ok = not missing and not mismatched
    return {"ok": ok, "skipped": False, "missing": missing, "mismatched": mismatched}
