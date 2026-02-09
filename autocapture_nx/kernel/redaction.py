"""Secret/token redaction helpers.

Raw-first local store is preserved; this is used only at explicit export/egress
boundaries (logs, diagnostics bundles, etc).
"""

from __future__ import annotations

import re
from typing import Any


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_sk", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9\-\._~\+\/]+=*")),
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
]

_SENSITIVE_KEYS = {
    # Keep this tight and explicit to avoid redacting non-secret config values
    # like "token_format" or "token_scope".
    "openai_api_key",
    "api_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
}


def redact_text(value: str) -> str:
    text = str(value or "")
    for _name, pattern in _PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def redact_obj(obj: Any) -> Any:
    if obj is None or isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, bytes):
        return obj
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, dict):
        redacted: dict[Any, Any] = {}
        for k, v in obj.items():
            try:
                key = str(k).casefold()
            except Exception:
                key = ""
            if key in _SENSITIVE_KEYS:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_obj(v)
        return redacted
    return redact_text(str(obj))
