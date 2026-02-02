"""SQLite-backed state vector index using the state tape store."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext

from .store_sqlite import StateTapeStore


@dataclass(frozen=True)
class StateVectorHit:
    state_id: str
    score: float


class SQLiteStateVectorIndex(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._store = _resolve_store(context)

    def capabilities(self) -> dict[str, Any]:
        return {"state.vector_index": self}

    def index_spans(self, _spans) -> dict[str, Any]:
        return {"indexed": 0}

    def query(
        self,
        query_embedding: list[float],
        *,
        filters: dict[str, Any] | None = None,
        k: int = 5,
    ) -> list[StateVectorHit]:
        if not query_embedding or self._store is None:
            return []
        filters = filters or {}
        spans = self._store.get_spans(
            session_id=filters.get("session_id"),
            start_ms=filters.get("start_ms"),
            end_ms=filters.get("end_ms"),
            app=filters.get("app"),
            limit=filters.get("limit"),
        )
        hits: list[StateVectorHit] = []
        for span in spans:
            emb = span.get("z_embedding", {})
            z_vec = _unpack_embedding(emb)
            score = _cosine(query_embedding, z_vec)
            hits.append(StateVectorHit(state_id=str(span.get("state_id")), score=float(score)))
        hits.sort(key=lambda h: (-h.score, h.state_id))
        return hits[: max(1, int(k))]


def _resolve_store(context: PluginContext) -> StateTapeStore | None:
    try:
        store = context.get_capability("storage.state_tape")
    except Exception:
        store = None
    return store


def _unpack_embedding(embedding: dict[str, Any]) -> list[float]:
    if not isinstance(embedding, dict):
        return []
    blob = embedding.get("blob")
    if isinstance(blob, str):
        import base64

        blob = base64.b64decode(blob.encode("ascii"))
    if not isinstance(blob, (bytes, bytearray)):
        return []
    data = bytes(blob)
    if not data:
        return []
    vec = []
    for idx in range(0, len(data), 2):
        vec.append(_f16_to_float(data[idx : idx + 2]))
    return vec


def _f16_to_float(blob: bytes) -> float:
    import struct

    if len(blob) != 2:
        return 0.0
    try:
        return float(struct.unpack("e", blob)[0])
    except Exception:
        return 0.0


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
