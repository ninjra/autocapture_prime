"""Screen Semantic Trace (SST) processing pipeline."""

from __future__ import annotations

__all__ = ["SSTPipeline", "SSTPipelineResult"]


def __getattr__(name: str):
    if name in __all__:
        from .pipeline import SSTPipeline, SSTPipelineResult

        return {"SSTPipeline": SSTPipeline, "SSTPipelineResult": SSTPipelineResult}[name]
    raise AttributeError(name)
