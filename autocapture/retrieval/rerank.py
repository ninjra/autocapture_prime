"""Simple reranker implementation."""

from __future__ import annotations

from typing import Any


class Reranker:
    def rerank(self, query: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_terms = query.lower().split()
        scored = []
        for doc in docs:
            text = str(doc.get("text", "")).lower()
            score = sum(text.count(term) for term in query_terms)
            scored.append({**doc, "score": score})
        scored.sort(key=lambda d: (-d["score"], d.get("doc_id", "")))
        return scored


def create_reranker(plugin_id: str) -> Reranker:
    return Reranker()
