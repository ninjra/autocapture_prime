"""Stable ID helpers for MX."""

from __future__ import annotations

import re
from typing import Any

from .hashing import hash_canonical, hash_text


_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")


def _normalize_kind(kind: str) -> str:
    if not _KIND_RE.match(kind):
        raise ValueError(f"Invalid kind '{kind}'. Use lowercase letters, digits, dot, dash, underscore.")
    return kind


def stable_id(kind: str, payload: Any) -> str:
    """Return a stable ID based on canonicalized payload."""
    norm = _normalize_kind(kind)
    return f"{norm}:{hash_canonical(payload)}"


def stable_id_from_text(kind: str, text: str) -> str:
    norm = _normalize_kind(kind)
    return f"{norm}:{hash_text(text)}"
