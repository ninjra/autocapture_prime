"""Answer verification for citations."""

from __future__ import annotations

from autocapture.memory.citations import CitationValidator, Citation


class Verifier:
    def __init__(self) -> None:
        self._validator = CitationValidator()

    def verify(self, claims: list[dict], span_ids: set[str]) -> None:
        for claim in claims:
            citations = [Citation(**c) if isinstance(c, dict) else c for c in claim.get("citations", [])]
            if not citations:
                raise ValueError("Claim missing citations")
            self._validator.validate(citations, span_ids)


def create_verifier(plugin_id: str) -> Verifier:
    return Verifier()
