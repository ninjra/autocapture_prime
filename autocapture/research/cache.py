"""Simple JSON cache for research scouting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ResearchCache:
    def __init__(self, root: str | Path = "artifacts/research_cache") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{_key_hash(key)}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, key: str, payload: dict[str, Any]) -> Path:
        path = self._path(key)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
