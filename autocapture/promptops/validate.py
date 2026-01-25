"""Prompt validation helpers."""

from __future__ import annotations

import re
from typing import Iterable


DEFAULT_BANNED = [
    "http://",
    "https://",
    "curl ",
    "wget ",
    "Invoke-WebRequest",
    "os.system",
    "subprocess",
]

JINJA_BANNED = [
    "__",
    "import",
    "attr",
    "class",
    "mro",
    "subclasses",
    "globals",
]


def _token_count(text: str) -> int:
    return len(text.split())


def validate_prompt(
    prompt: str,
    *,
    max_chars: int = 8000,
    max_tokens: int = 2000,
    banned_patterns: Iterable[str] | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    if len(prompt) > max_chars:
        errors.append("too_long")
    if _token_count(prompt) > max_tokens:
        errors.append("token_budget_exceeded")

    for pattern in banned_patterns or DEFAULT_BANNED:
        if pattern.lower() in prompt.lower():
            errors.append(f"banned_pattern:{pattern}")

    if "{%" in prompt:
        errors.append("jinja_control_block_disallowed")
    if "{{" in prompt:
        lowered = prompt.lower()
        for token in JINJA_BANNED:
            if token in lowered:
                errors.append(f"jinja_unsafe:{token}")
                break

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "stats": {"chars": len(prompt), "tokens": _token_count(prompt)},
    }
