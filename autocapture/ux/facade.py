"""Legacy UX facade for CLI + Web parity (deprecated; use autocapture_nx.ux.facade)."""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
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

_DEPRECATION_WARNED = False


def _warn_legacy() -> None:
    global _DEPRECATION_WARNED
    if _DEPRECATION_WARNED:
        return
    warnings.warn(
        "autocapture.ux.facade is deprecated; use autocapture_nx.ux.facade instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _DEPRECATION_WARNED = True


class UXFacade:
    def __init__(self, config: dict[str, Any]) -> None:
        _warn_legacy()
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

    @contextmanager
    def _kernel_context(self):
        from autocapture_nx.kernel.loader import Kernel, default_config_paths as nx_paths

        kernel = Kernel(nx_paths(), safe_mode=False)
        system = kernel.boot(start_conductor=False)
        try:
            yield system
        finally:
            kernel.shutdown()

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

    def resolve_citations(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        with self._kernel_context() as system:
            validator = system.get("citation.validator")
            return validator.resolve(citations)

    def verify_citations(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.resolve_citations(citations)
        return {"ok": bool(result.get("ok")), "errors": result.get("errors", [])}

    def verify_ledger(self, path: str | None = None) -> dict[str, Any]:
        from autocapture.pillars.citable import verify_ledger

        if path:
            ledger_path = Path(path)
        else:
            data_dir = Path(self.config.get("storage", {}).get("data_dir", "data"))
            ledger_path = data_dir / "ledger.ndjson"
        ok, errors = verify_ledger(ledger_path)
        return {"ok": ok, "errors": errors, "path": str(ledger_path)}

    def verify_anchors(self, path: str | None = None) -> dict[str, Any]:
        from autocapture.pillars.citable import verify_anchors

        with self._kernel_context() as system:
            config = system.config if hasattr(system, "config") else {}
            anchor_cfg = config.get("storage", {}).get("anchor", {})
            anchor_path = Path(path) if path else Path(anchor_cfg.get("path", "anchor/anchors.ndjson"))
            keyring = system.get("storage.keyring") if system.has("storage.keyring") else None
            ok, errors = verify_anchors(anchor_path, keyring)
            return {"ok": ok, "errors": errors, "path": str(anchor_path)}

    def verify_evidence(self) -> dict[str, Any]:
        from autocapture.pillars.citable import verify_evidence

        with self._kernel_context() as system:
            metadata = system.get("storage.metadata")
            media = system.get("storage.media")
            ok, errors = verify_evidence(metadata, media)
            return {"ok": ok, "errors": errors}

    def export_proof_bundle(
        self,
        evidence_ids: list[str],
        output_path: str,
        *,
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from dataclasses import asdict
        from autocapture_nx.kernel.proof_bundle import export_proof_bundle

        with self._kernel_context() as system:
            config = system.config if hasattr(system, "config") else {}
            storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
            data_dir = storage_cfg.get("data_dir", "data")
            ledger_path = Path(data_dir) / "ledger.ndjson"
            anchor_path = Path(storage_cfg.get("anchor", {}).get("path", "anchor/anchors.ndjson"))
            report = export_proof_bundle(
                metadata=system.get("storage.metadata"),
                media=system.get("storage.media"),
                keyring=system.get("storage.keyring") if system.has("storage.keyring") else None,
                ledger_path=ledger_path,
                anchor_path=anchor_path,
                output_path=output_path,
                evidence_ids=evidence_ids,
                citations=citations,
            )
            return asdict(report)

    def replay_proof_bundle(self, bundle_path: str) -> dict[str, Any]:
        from dataclasses import asdict
        from autocapture_nx.kernel.replay import replay_bundle

        return asdict(replay_bundle(bundle_path))

    def settings_schema(self) -> dict[str, Any]:
        return get_schema()

    def plugin_options(self) -> dict[str, Any]:
        return build_plugin_options(self.config)

    def doctor_report(self) -> DoctorReport:
        from autocapture_nx.kernel.loader import Kernel, default_config_paths as nx_paths

        kernel = Kernel(nx_paths(), safe_mode=False)
        kernel.boot(start_conductor=False)
        checks = kernel.doctor()
        report_checks = [DoctorCheck(name=c.name, ok=c.ok, detail=c.detail) for c in checks]
        ok = all(c.ok for c in report_checks)
        return DoctorReport(ok=ok, generated_at_utc=datetime.now(timezone.utc).isoformat(), checks=report_checks)


def create_facade() -> UXFacade:
    _warn_legacy()
    config = load_config(default_config_paths(), safe_mode=False)
    return UXFacade(config)
