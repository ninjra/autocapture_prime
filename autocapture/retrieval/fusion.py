"""Fusion utilities for retrieval."""

from __future__ import annotations

from typing import Any


def rrf_fusion(rankings: list[list[dict[str, Any]]], k: int = 60) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for idx, item in enumerate(ranking):
            doc_id = item.get("doc_id") or item.get("record_id")
            if doc_id is None:
                continue
            scores.setdefault(doc_id, 0.0)
            scores[doc_id] += 1.0 / (k + idx + 1)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"doc_id": doc_id, "score": score} for doc_id, score in ordered]
