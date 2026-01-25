"""Tiered retrieval planner."""

from __future__ import annotations

from typing import Any

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex
from autocapture.retrieval.fusion import rrf_fusion
from autocapture.retrieval.rerank import Reranker
from autocapture.retrieval.signals import RetrievalTrace


class TieredRetriever:
    def __init__(
        self,
        lexical: LexicalIndex,
        vector: VectorIndex,
        reranker: Reranker,
        fast_threshold: int = 3,
        fusion_threshold: int = 5,
    ) -> None:
        self.lexical = lexical
        self.vector = vector
        self.reranker = reranker
        self.fast_threshold = fast_threshold
        self.fusion_threshold = fusion_threshold

    def retrieve(self, query: str) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        fast_hits = self.lexical.query(query)
        trace.append({"tier": "FAST", "reason": "lexical", "result_count": len(fast_hits)})
        if len(fast_hits) >= self.fast_threshold:
            return {"results": fast_hits, "trace": trace}
        vector_hits = [{"doc_id": hit.doc_id, "score": hit.score} for hit in self.vector.query(query)]
        fused = rrf_fusion([fast_hits, vector_hits])
        trace.append({"tier": "FUSION", "reason": "rrf", "result_count": len(fused)})
        if len(fused) >= self.fusion_threshold:
            return {"results": fused, "trace": trace}
        reranked = self.reranker.rerank(query, fused)
        trace.append({"tier": "RERANK", "reason": "low_recall", "result_count": len(reranked)})
        return {"results": reranked, "trace": trace}


def create_retrieval_strategy(plugin_id: str) -> TieredRetriever:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config
    from autocapture.indexing.lexical import LexicalIndex
    from autocapture.indexing.vector import VectorIndex, LocalEmbedder
    from autocapture.retrieval.rerank import Reranker

    config = load_config(default_config_paths(), safe_mode=False)
    lexical_path = config.get("storage", {}).get("lexical_path", "data/lexical.db")
    vector_path = config.get("storage", {}).get("vector_path", "data/vector.db")
    embedder = LocalEmbedder(config.get("indexing", {}).get("embedder_model"))
    lexical = LexicalIndex(lexical_path)
    vector = VectorIndex(vector_path, embedder)
    reranker = Reranker()
    return TieredRetriever(lexical, vector, reranker)
