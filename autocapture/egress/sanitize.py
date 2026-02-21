"""Export/egress sanitization utilities.

Raw-first local store: these helpers are used only on explicit export/egress
pathways. They are deterministic given the provided key material.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from autocapture.privacy.redaction import RedactionEntry, redact_text


def sanitize_json_for_export(
    payload: Any,
    *,
    key: bytes,
    recognizers: Iterable[str] | None = None,
) -> tuple[Any, list[RedactionEntry]]:
    """Recursively redact strings within a JSON-like payload."""

    entries: list[RedactionEntry] = []

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            res = redact_text(node, key=key, recognizers=recognizers)
            entries.extend(res.entries)
            return res.text
        if isinstance(node, list):
            return [_walk(x) for x in node]
        if isinstance(node, tuple):
            return [_walk(x) for x in node]
        if isinstance(node, dict):
            return {str(k): _walk(v) for k, v in node.items()}
        return node

    return _walk(payload), entries


def redaction_metadata(entries: list[RedactionEntry]) -> dict[str, Any]:
    """Convert redaction entries into a JSON-serializable metadata object."""

    # Do not include raw values; only deterministic tokens and HMAC digests.
    return {
        "redaction_entries": [asdict(entry) for entry in entries],
    }

