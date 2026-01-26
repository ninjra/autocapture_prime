"""Context pack formats for MX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContextPack:
    spans: list[dict[str, Any]]
    signals: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {"format": "json", "spans": self.spans, "signals": self.signals}

    def to_tron(self) -> str:
        lines = ["TRON/1.0"]
        for span in self.spans:
            span_id = span.get("span_id") or span.get("id")
            text = span.get("text", "")
            lines.append(f"SPAN {span_id} {text}")
        return "\n".join(lines)


def build_context_pack(spans: list[dict[str, Any]], signals: dict[str, Any]) -> ContextPack:
    return ContextPack(spans=spans, signals=signals)
