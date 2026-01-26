"""Run-scoped ID helpers."""

from __future__ import annotations

import uuid
import base64
from typing import Any


ENC_PREFIX = "rid_"


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


def encode_record_id_component(value: str) -> str:
    token = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{ENC_PREFIX}{token}"


def decode_record_id_component(value: str) -> str:
    if not value.startswith(ENC_PREFIX):
        return value
    raw = value[len(ENC_PREFIX) :]
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return value
