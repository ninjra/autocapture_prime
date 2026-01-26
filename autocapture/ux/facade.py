"""UX facade for CLI + Web parity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autocapture.config.defaults import default_config_paths
from autocapture.config.load import load_config
from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex, LocalEmbedder
from autocapture.memory.answer_orchestrator import AnswerOrchestrator
from autocapture.memory.context_pack import build_context_pack
from autocapture.retrieval.rerank import Reranker
from autocapture.retrieval.tiers import TieredRetriever
from autocapture.ux.models import DoctorCheck, DoctorReport
from autocapture.ux.settings_schema import get_schema
from autocapture.ux.plugin_options import build_plugin_options


class UXFacade:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._retriever = TieredRetriever(
            LexicalIndex(config.get("storage", {}).get("lexical_path", "data/lexical.db")),
            VectorIndex(
                config.get("storage", {}).get("vector_path", "data/vector.db"),
                LocalEmbedder(config.get("indexing", {}).get("embedder_model")),
            ),
            Reranker(),
        )
        self._answer = AnswerOrchestrator()

    def query(self, text: str) -> dict[str, Any]:
        retrieval = self._retriever.retrieve(text)
        results = retrieval["results"]
        trace = retrieval["trace"]
        spans = []
        for item in results:
            span_id = item.get("doc_id") or item.get("record_id") or item.get("span_id")
            if span_id is None:
                continue
            spans.append({"span_id": span_id, "text": item.get("snippet", "")})
        context = build_context_pack(spans, {"trace": trace}).to_json()
        if not spans:
            return {"answer": {"claims": []}, "citations": [], "provenance": context}
        span_ids = {span["span_id"] for span in spans}
        claims = [
            {
                "text": f"Found {len(spans)} evidence items for query.",
                "citations": [{"span_id": span_id} for span_id in span_ids],
            }
        ]
        answer = self._answer.build_answer(claims, span_ids)
        return {"answer": answer, "citations": claims[0]["citations"], "provenance": context}

    def settings_schema(self) -> dict[str, Any]:
        return get_schema()

    def plugin_options(self) -> dict[str, Any]:
        return build_plugin_options(self.config)

    def doctor_report(self) -> DoctorReport:
        from autocapture_nx.kernel.loader import Kernel, default_config_paths as nx_paths

        kernel = Kernel(nx_paths(), safe_mode=False)
        kernel.boot()
        checks = kernel.doctor()
        report_checks = [DoctorCheck(name=c.name, ok=c.ok, detail=c.detail) for c in checks]
        ok = all(c.ok for c in report_checks)
        return DoctorReport(ok=ok, generated_at_utc=datetime.now(timezone.utc).isoformat(), checks=report_checks)


def create_facade() -> UXFacade:
    config = load_config(default_config_paths(), safe_mode=False)
    return UXFacade(config)
