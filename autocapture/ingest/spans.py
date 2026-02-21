"""Span definitions and store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture.core.ids import stable_id


@dataclass(frozen=True)
class Span:
    span_id: str
    text: str
    bbox: dict[str, float] | None
    source: dict[str, Any]


def _bbox_id(bbox: dict[str, float] | None) -> dict[str, int] | None:
    if bbox is None:
        return None
    return {key: int(round(value * 1_000_000)) for key, value in bbox.items()}


def build_span(text: str, bbox: dict[str, float] | None, source: dict[str, Any]) -> Span:
    payload = {"text": text, "bbox": _bbox_id(bbox), "source": source}
    span_id = stable_id("span", payload)
    return Span(span_id=span_id, text=text, bbox=bbox, source=source)


class SpanStore:
    def __init__(self) -> None:
        self._spans: dict[str, Span] = {}

    def add(self, span: Span) -> None:
        self._spans[span.span_id] = span

    def get(self, span_id: str) -> Span | None:
        return self._spans.get(span_id)

    def list(self) -> list[Span]:
        return list(self._spans.values())


def create_span_store(plugin_id: str) -> SpanStore:
    return SpanStore()
