"""Plugin kind registry for MX."""

from __future__ import annotations

REQUIRED_KINDS = [
    "capture.source",
    "capture.encoder",
    "activity.signal",
    "storage.blob_backend",
    "storage.media_backend",
    "spans_v2.backend",
    "ocr.engine",
    "llm.provider",
    "decode.backend",
    "embedder.text",
    "vector.backend",
    "retrieval.strategy",
    "reranker.provider",
    "compressor",
    "verifier",
    "egress.sanitizer",
    "export.bundle",
    "import.bundle",
    "ui.panel",
    "ui.overlay",
    "prompt.bundle",
    "training.pipeline",
    "research.source",
    "research.watchlist",
]

SUPPORT_KINDS = sorted({
    *REQUIRED_KINDS,
    "vision.extractor",
    "table.extractor",
    "graph.adapter",
    "agent.job",
    "storage.metadata",
    "storage.entity_map",
    "runtime.governor",
    "runtime.scheduler",
    "time.intent_parser",
})


def is_required(kind: str) -> bool:
    return kind in REQUIRED_KINDS


def all_kinds() -> list[str]:
    return list(SUPPORT_KINDS)
