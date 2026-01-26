"""Deterministic hashing utilities for MX."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any


class CanonicalJSONError(ValueError):
    """Raised when input cannot be canonicalized."""


def _normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise CanonicalJSONError("NaN/Inf not allowed in canonical JSON")
        raise CanonicalJSONError("Floats are not permitted in canonical JSON")
    return obj


def canonical_dumps(obj: Any) -> str:
    normalized = _normalize(obj)
    return json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def canonical_bytes(obj: Any) -> bytes:
    return canonical_dumps(obj).encode("utf-8")


def _blake3_hash(data: bytes) -> str | None:
    try:
        import blake3  # type: ignore
    except Exception:
        return None
    return blake3.blake3(data).hexdigest()


def hash_bytes(data: bytes) -> str:
    digest = _blake3_hash(data)
    if digest is not None:
        return digest
    return hashlib.sha256(data).hexdigest()


def hash_canonical(obj: Any) -> str:
    return hash_bytes(canonical_bytes(obj))


def hash_text(text: str) -> str:
    return hash_bytes(text.encode("utf-8"))
