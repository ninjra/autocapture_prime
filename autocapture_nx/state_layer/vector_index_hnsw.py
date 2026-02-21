"""Deterministic snapshot-based vector index (HNSW-compatible interface)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from autocapture_nx.plugin_system.api import PluginBase, PluginContext

from .ids import compute_embedding_hash
from .store_sqlite import StateTapeStore
from .vector_index import StateVectorHit


@dataclass(frozen=True)
class _VectorEntry:
    state_id: str
    vector: list[float]
    embedding_hash: str
    model_version: str
    session_id: str
    ts_start_ms: int
    ts_end_ms: int
    app: str


class HNSWStateVectorIndex(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        state_cfg = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}
        index_cfg = state_cfg.get("index", {}) if isinstance(state_cfg.get("index", {}), dict) else {}
        self._store = _resolve_store(context)
        self._max_candidates = int(index_cfg.get("max_candidates", 200) or 200)
        self._bucket_dims = 16
        self._entries: dict[str, _VectorEntry] = {}
        self._buckets: dict[str, list[str]] = {}
        self._sorted_state_ids: list[str] = []
        self._snapshot_marker: dict[str, Any] | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"state.vector_index": self}

    def index_spans(self, spans) -> dict[str, Any]:
        spans_list = [s for s in spans if isinstance(s, dict)]
        if spans_list:
            self._add_entries(spans_list)
        if self._store is not None:
            try:
                self._snapshot_marker = self._store.get_snapshot_marker()
            except Exception:
                self._snapshot_marker = None
        return {"indexed": len(spans_list)}

    def clear(self) -> None:
        self._entries = {}
        self._buckets = {}
        self._sorted_state_ids = []
        self._snapshot_marker = None

    def query(
        self,
        query_embedding: list[float],
        *,
        filters: dict[str, Any] | None = None,
        k: int = 5,
    ) -> list[StateVectorHit]:
        if not query_embedding:
            return []
        if not self._entries and self._store is not None:
            self._build_from_store()
        if not self._entries:
            return []
        if self._store is not None and self._snapshot_marker is not None:
            try:
                current = self._store.get_snapshot_marker()
            except Exception:
                current = None
            if current is None or not _marker_equal(self._snapshot_marker, current):
                self._build_from_store()
                if self._snapshot_marker is None or (current is not None and not _marker_equal(self._snapshot_marker, current)):
                    return []

        query_vec = _normalize(query_embedding)
        candidates = self._candidate_ids(query_vec)
        entries = self._filter_entries(candidates, filters or {})
        if not entries:
            entries = self._filter_entries(self._sorted_state_ids, filters or {})
        hits: list[StateVectorHit] = []
        for entry in entries:
            score = _cosine(query_vec, entry.vector)
            hits.append(StateVectorHit(state_id=entry.state_id, score=float(score)))
        hits.sort(key=lambda h: (-h.score, h.state_id))
        return hits[: max(1, int(k))]

    def _build_from_store(self) -> None:
        if self._store is None:
            return
        spans = self._store.get_spans()
        self.clear()
        if spans:
            self._add_entries(spans)
        try:
            self._snapshot_marker = self._store.get_snapshot_marker()
        except Exception:
            self._snapshot_marker = None

    def _add_entries(self, spans: Iterable[dict[str, Any]]) -> None:
        for span in spans:
            entry = _entry_from_span(span)
            if entry is None:
                continue
            self._entries[entry.state_id] = entry
        self._sorted_state_ids = sorted(self._entries.keys())
        self._rebuild_buckets()

    def _rebuild_buckets(self) -> None:
        buckets: dict[str, list[str]] = {}
        for entry in self._entries.values():
            key = _bucket_key(entry.vector, self._bucket_dims)
            buckets.setdefault(key, []).append(entry.state_id)
        for key in list(buckets.keys()):
            buckets[key].sort()
        self._buckets = buckets

    def _candidate_ids(self, query_vec: list[float]) -> list[str]:
        if not self._entries:
            return []
        key = _bucket_key(query_vec, self._bucket_dims)
        candidate_ids: list[str] = []
        seen: set[str] = set()
        for sid in self._buckets.get(key, []):
            if sid not in seen:
                candidate_ids.append(sid)
                seen.add(sid)
            if self._max_candidates > 0 and len(candidate_ids) >= self._max_candidates:
                return candidate_ids
        for neighbor in _neighbor_keys(key):
            for sid in self._buckets.get(neighbor, []):
                if sid not in seen:
                    candidate_ids.append(sid)
                    seen.add(sid)
                if self._max_candidates > 0 and len(candidate_ids) >= self._max_candidates:
                    return candidate_ids
        if self._max_candidates > 0 and len(candidate_ids) < self._max_candidates:
            for sid in self._sorted_state_ids:
                if sid not in seen:
                    candidate_ids.append(sid)
                    seen.add(sid)
                if len(candidate_ids) >= self._max_candidates:
                    break
        return candidate_ids

    def _filter_entries(self, state_ids: Iterable[str], filters: dict[str, Any]) -> list[_VectorEntry]:
        session_id = filters.get("session_id")
        start_ms = filters.get("start_ms")
        end_ms = filters.get("end_ms")
        app = filters.get("app")
        filtered: list[_VectorEntry] = []
        for sid in state_ids:
            entry = self._entries.get(str(sid))
            if entry is None:
                continue
            if session_id and entry.session_id != session_id:
                continue
            if start_ms is not None and entry.ts_end_ms < int(start_ms):
                continue
            if end_ms is not None and entry.ts_start_ms > int(end_ms):
                continue
            if app and entry.app != app:
                continue
            filtered.append(entry)
        return filtered


def _resolve_store(context: PluginContext) -> StateTapeStore | None:
    try:
        store = context.get_capability("storage.state_tape")
    except Exception:
        store = None
    return store


def _entry_from_span(span: dict[str, Any]) -> _VectorEntry | None:
    if not isinstance(span, dict):
        return None
    state_id = str(span.get("state_id") or "")
    if not state_id:
        return None
    emb = span.get("z_embedding", {}) if isinstance(span.get("z_embedding"), dict) else {}
    blob = _embedding_blob(emb)
    if not blob:
        return None
    vector = _normalize(_unpack_embedding(emb))
    if not vector:
        return None
    summary = span.get("summary_features", {}) if isinstance(span.get("summary_features"), dict) else {}
    app = str(summary.get("app") or "")
    prov = span.get("provenance", {}) if isinstance(span.get("provenance"), dict) else {}
    model_version = str(prov.get("model_version") or "")
    return _VectorEntry(
        state_id=state_id,
        vector=vector,
        embedding_hash=compute_embedding_hash(blob),
        model_version=model_version,
        session_id=str(span.get("session_id") or ""),
        ts_start_ms=int(span.get("ts_start_ms", 0) or 0),
        ts_end_ms=int(span.get("ts_end_ms", 0) or 0),
        app=app,
    )


def _embedding_blob(embedding: dict[str, Any]) -> bytes:
    if not isinstance(embedding, dict):
        return b""
    blob = embedding.get("blob")
    if isinstance(blob, str):
        import base64

        return base64.b64decode(blob.encode("ascii"))
    if isinstance(blob, (bytes, bytearray)):
        return bytes(blob)
    return b""


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
    vec: list[float] = []
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


def _normalize(vec: list[float]) -> list[float]:
    if not vec:
        return []
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _bucket_key(vec: list[float], dims: int) -> str:
    if not vec:
        return ""
    length = min(len(vec), max(1, int(dims)))
    bits = ["1" if vec[i] >= 0.0 else "0" for i in range(length)]
    return "".join(bits)


def _neighbor_keys(key: str) -> list[str]:
    if not key:
        return []
    neighbors: list[str] = []
    chars = list(key)
    for idx, ch in enumerate(chars):
        flipped = "1" if ch == "0" else "0"
        neighbor = "".join(chars[:idx] + [flipped] + chars[idx + 1 :])
        neighbors.append(neighbor)
    return neighbors


def _marker_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return False
    keys = (
        "span_count",
        "max_ts_end_ms",
        "latest_state_id",
        "latest_embedding_hash",
        "latest_model_version",
    )
    return all(left.get(k) == right.get(k) for k in keys)
