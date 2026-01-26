"""Run-scoped ID helpers."""

from __future__ import annotations

import uuid
from typing import Any


def new_run_id() -> str:
    return uuid.uuid4().hex


def ensure_run_id(config: dict[str, Any]) -> str:
    runtime = config.setdefault("runtime", {})
    run_id = runtime.get("run_id")
    if not run_id:
        run_id = new_run_id()
        runtime["run_id"] = run_id
    return str(run_id)


def prefixed_id(run_id: str, kind: str, seq: int) -> str:
    return f"{run_id}/{kind}/{int(seq)}"


def ensure_prefixed(run_id: str, value: str) -> str:
    prefix = f"{run_id}/"
    if value.startswith(prefix):
        return value
    return f"{prefix}{value}"
