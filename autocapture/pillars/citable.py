"""Citable ledger utilities."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture.core.hashing import canonical_dumps


@dataclass
class LedgerEntry:
    payload: dict[str, Any]
    entry_hash: str


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash: str | None = None
        if self.path.exists():
            self._last_hash = self._scan_last_hash()

    def _scan_last_hash(self) -> str | None:
        last = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                last = entry.get("entry_hash", last)
        return last

    def append(self, entry: dict[str, Any]) -> str:
        required = {"schema_version", "entry_id", "ts_utc", "stage", "inputs", "outputs", "policy_snapshot_hash"}
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"Ledger entry missing fields: {sorted(missing)}")
        payload = dict(entry)
        prev_hash = self._last_hash
        payload["prev_hash"] = prev_hash
        payload.pop("entry_hash", None)
        canonical = canonical_dumps(payload)
        entry_hash = hashlib.sha256((canonical + (prev_hash or "")).encode("utf-8")).hexdigest()
        payload["entry_hash"] = entry_hash
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        self._last_hash = entry_hash
        return entry_hash


def verify_ledger(path: str | Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    prev_hash: str | None = None
    with Path(path).open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if not line.strip():
                continue
            entry = json.loads(line)
            entry_hash = entry.get("entry_hash")
            payload = dict(entry)
            payload.pop("entry_hash", None)
            canonical = canonical_dumps(payload)
            expected = hashlib.sha256((canonical + (prev_hash or "")).encode("utf-8")).hexdigest()
            if entry_hash != expected:
                errors.append(f"hash_mismatch:{idx}")
            prev_hash = entry_hash
    return len(errors) == 0, errors
