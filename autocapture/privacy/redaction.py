"""Deterministic redaction primitives for export/egress boundaries.

Raw data is stored locally (raw-first). Redaction occurs only when explicitly
exporting/egressing, and produces a redaction map that can be attached to the
export metadata for audit/citeability without leaking original PII.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Iterable


_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b")
_RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_RE_CREDIT_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


DEFAULT_RECOGNIZERS: dict[str, re.Pattern[str]] = {
    "email": _RE_EMAIL,
    "phone": _RE_PHONE,
    "ssn": _RE_SSN,
    "credit_card": _RE_CREDIT_CARD,
}


@dataclass(frozen=True)
class RedactionEntry:
    kind: str
    token: str
    value_hmac_b32: str


@dataclass(frozen=True)
class RedactionResult:
    text: str
    entries: list[RedactionEntry]


def _b32_no_pad(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _value_hmac(key: bytes, *, kind: str, value: str) -> bytes:
    msg = f"{kind}|{value}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).digest()


def _token_for(key: bytes, *, kind: str, value: str) -> str:
    digest = _value_hmac(key, kind=kind, value=value)
    return f"⟦REDACTED:{kind.upper()}:{_b32_no_pad(digest[:10])}⟧"


def redact_text(
    text: str,
    *,
    key: bytes,
    recognizers: Iterable[str] | None = None,
) -> RedactionResult:
    """Redact PII-like strings in `text` deterministically.

    `entries` intentionally does not contain raw values.
    """

    if not text:
        return RedactionResult(text="", entries=[])
    active = list(recognizers) if recognizers is not None else list(DEFAULT_RECOGNIZERS.keys())
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for name in active:
        pat = DEFAULT_RECOGNIZERS.get(str(name))
        if pat is not None:
            patterns.append((str(name), pat))

    spans: list[tuple[int, int, str, str]] = []
    for kind, pat in patterns:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), kind, m.group(0)))
    if not spans:
        return RedactionResult(text=text, entries=[])

    # Resolve overlaps deterministically: sort by start, then longer match first.
    spans.sort(key=lambda row: (row[0], -(row[1] - row[0]), row[2]))
    kept: list[tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, kind, value in spans:
        if start < last_end:
            continue
        kept.append((start, end, kind, value))
        last_end = end

    out_parts: list[str] = []
    cursor = 0
    entries: list[RedactionEntry] = []
    for start, end, kind, value in kept:
        out_parts.append(text[cursor:start])
        token = _token_for(key, kind=kind, value=value)
        out_parts.append(token)
        cursor = end
        entries.append(
            RedactionEntry(
                kind=kind,
                token=token,
                value_hmac_b32=_b32_no_pad(_value_hmac(key, kind=kind, value=value)),
            )
        )
    out_parts.append(text[cursor:])
    return RedactionResult(text="".join(out_parts), entries=entries)

