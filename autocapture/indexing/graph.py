"""Graph adapter interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str


class GraphAdapter:
    def __init__(self) -> None:
        self._adj: dict[str, list[GraphEdge]] = {}

    def add_edge(self, source: str, target: str, relation: str) -> None:
        edge = GraphEdge(source=source, target=target, relation=relation)
        self._adj.setdefault(source, []).append(edge)

    def neighbors(self, source: str) -> list[GraphEdge]:
        return list(self._adj.get(source, []))

    def nodes(self) -> list[str]:
        return sorted(self._adj.keys())


def create_graph_adapter(plugin_id: str) -> GraphAdapter:
    return GraphAdapter()
