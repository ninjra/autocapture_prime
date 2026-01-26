"""Citation models and validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    span_id: str
    source_id: str | None = None


class CitationValidator:
    def validate(self, citations: list[Citation], span_ids: set[str]) -> None:
        for citation in citations:
            if citation.span_id not in span_ids:
                raise ValueError(f"Unknown span id: {citation.span_id}")
