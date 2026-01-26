"""Prompt evaluation harness."""

from __future__ import annotations

from typing import Any, Iterable


def evaluate_prompt(
    prompt: str,
    examples: Iterable[dict[str, Any]],
    *,
    min_pass_rate: float = 1.0,
    require_citations: bool = True,
) -> dict[str, Any]:
    total = 0
    passed = 0
    citation_hits = 0
    for example in examples:
        total += 1
        required = example.get("required_tokens", [])
        hit = all(token.lower() in prompt.lower() for token in required)
        if hit:
            passed += 1
        needs_citation = example.get("requires_citation", require_citations)
        if needs_citation:
            if "[citation]" in prompt.lower() or "[source]" in prompt.lower():
                citation_hits += 1
    pass_rate = passed / total if total else 1.0
    citation_coverage = citation_hits / total if total else 1.0
    ok = pass_rate >= min_pass_rate and (citation_coverage > 0 or not require_citations)
    return {
        "ok": ok,
        "pass_rate": pass_rate,
        "citation_coverage": citation_coverage,
        "total": total,
        "passed": passed,
    }
