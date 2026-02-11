"""Append-only NDJSON facts sink for canonical derived records.

This is a durable, raw-first store meant to complement SQLite indexes/records.
It is intentionally append-only (no pruning/deletes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps


@dataclass(frozen=True)
class FactsAppendResult:
    ok: bool
    path: str
    bytes_written: int
    error: str | None = None


def _resolve_facts_path(config: dict[str, Any], *, default_rel: str) -> Path:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = storage.get("data_dir", "data") if isinstance(storage, dict) else "data"
    root = Path(str(data_dir))
    # Default: <DataRoot>/facts/<default_rel>
    facts_dir = storage.get("facts_dir", "facts") if isinstance(storage, dict) else "facts"
    return root / str(facts_dir) / default_rel


def append_fact_line(
    config: dict[str, Any],
    *,
    rel_path: str,
    payload: dict[str, Any],
) -> FactsAppendResult:
    """Append one canonical JSON record as a single NDJSON line."""

    try:
        line = dumps(payload) + "\n"
    except Exception as exc:
        return FactsAppendResult(ok=False, path="", bytes_written=0, error=f"canonical_json_error:{type(exc).__name__}:{exc}")

    path = _resolve_facts_path(config, default_rel=rel_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return FactsAppendResult(ok=False, path=str(path), bytes_written=0, error=f"mkdir_failed:{type(exc).__name__}:{exc}")

    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    fsync_policy = str(storage.get("fsync_policy", "none") if isinstance(storage, dict) else "none").lower()

    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            if fsync_policy in {"bulk", "critical"}:
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    # Best-effort: do not fail facts persistence due to fsync.
                    pass
    except Exception as exc:
        return FactsAppendResult(ok=False, path=str(path), bytes_written=0, error=f"append_failed:{type(exc).__name__}:{exc}")

    return FactsAppendResult(ok=True, path=str(path), bytes_written=len(line.encode("utf-8")), error=None)

