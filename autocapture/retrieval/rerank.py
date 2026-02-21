"""Simple reranker implementation."""

from __future__ import annotations

from typing import Any


class Reranker:
    def rerank(self, query: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_text = str(query or "").strip().lower()
        terms = [t for t in query_text.split() if t]
        scored: list[dict[str, Any]] = []
        for doc in docs:
            base = float(doc.get("score", 0.0) or 0.0)
            text = str(doc.get("text", ""))
            text_norm = text.strip().lower()
            overlap = 0.0
            if terms:
                overlap = float(sum(1 for term in set(terms) if term in text_norm))
            phrase_bonus = 2.0 if query_text and query_text in text_norm else 0.0
            exact_bonus = 1.0 if query_text and query_text == text_norm else 0.0
            score = base + overlap + phrase_bonus + exact_bonus
            scored.append({**doc, "score": score})
        scored.sort(key=lambda d: (-float(d.get("score", 0.0)), str(d.get("doc_id", ""))))
        return scored


def create_reranker(plugin_id: str) -> Reranker:
    return Reranker()
