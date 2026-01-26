"""Preview tokenization for settings UX."""

from __future__ import annotations

from autocapture.ux.redaction import EgressSanitizer


def preview_tokens(text: str, config: dict) -> dict:
    sanitizer = EgressSanitizer(config)
    result = sanitizer.sanitize_text(text)
    return {
        "text": result["text"],
        "tokens": result["tokens"],
        "glossary": result["glossary"],
    }
