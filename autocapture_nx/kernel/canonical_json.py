"""Canonical JSON serialization per blueprint constraints."""

from __future__ import annotations

import json
import math
import unicodedata
from typing import Any


class CanonicalJSONError(ValueError):
    pass


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
        # Disallow floats to avoid unstable encodings.
        raise CanonicalJSONError("Floats are not permitted in canonical JSON")
    return obj


def dumps(obj: Any) -> str:
    """Return canonical JSON string with sorted keys and no whitespace."""
    normalized = _normalize(obj)
    return json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def sha256_bytes(obj: Any) -> bytes:
    import hashlib

    data = dumps(obj).encode("utf-8")
    return hashlib.sha256(data).digest()
