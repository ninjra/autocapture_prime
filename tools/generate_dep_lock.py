"""Generate a deterministic dependency lock file from pyproject.toml."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib


LOCK_PATH = Path("requirements.lock.json")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_lock(pyproject_path: Path = Path("pyproject.toml")) -> dict[str, Any]:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    deps = sorted(project.get("dependencies", []) or [])
    optional = project.get("optional-dependencies", {}) or {}
    optional_sorted = {key: sorted(value or []) for key, value in sorted(optional.items())}
    payload = {
        "version": 1,
        "python": project.get("requires-python"),
        "dependencies": deps,
        "optional_dependencies": optional_sorted,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    lock = dict(payload)
    lock["content_hash"] = digest
    lock["generated_at"] = datetime.now(timezone.utc).isoformat()
    return lock


def main() -> int:
    lock = build_lock()
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {LOCK_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
