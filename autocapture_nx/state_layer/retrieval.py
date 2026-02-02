"""State-layer retrieval over the state tape."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from autocapture.indexing.vector import LocalEmbedder
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

from .ids import compute_config_hash
from .jepa_model import JEPAModel
from .store_sqlite import StateTapeStore
from .policy_gate import StatePolicyGate


class StateRetrieval(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._config = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}
        self._store = _resolve_store(context)
        self._vector_index = _resolve_vector_index(context)
        self._policy_gate = StatePolicyGate(cfg)
        self._embedder = None
        self._embedder_identity: dict[str, Any] = {}
        self._model_version: str | None = None
        self._config_hash = compute_config_hash(self._config.get("builder", {}) if isinstance(self._config.get("builder", {}), dict) else {})
        self._last_trace: list[dict[str, Any]] = []
        self._jepa_model: JEPAModel | None = None
        self._init_embedder()
        self._maybe_load_jepa_model()

    def capabilities(self) -> dict[str, Any]:
        return {"state.retrieval": self}

    def trace(self) -> list[dict[str, Any]]:
        return list(self._last_trace)

    def search(
        self,
        query: str,
        *,
        time_window: dict[str, Any] | None = None,
        app_filter: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        query_text = str(query or "").strip()
        if not query_text:
            return []
        store = self._store
        if store is None:
            trace.append({"tier": "MISSING_STORE"})
            self._last_trace = trace
            return []
        policy = self._policy_gate.decide()
        if app_filter and not self._policy_gate.app_allowed(app_filter, policy):
            trace.append({"tier": "APP_BLOCKED", "app": app_filter})
            self._last_trace = trace
            return []
        query_vec = self._embed_query(query_text, use_jepa=True)
        if not query_vec:
            trace.append({"tier": "EMPTY_QUERY_EMBEDDING"})
            self._last_trace = trace
            return []
        cfg_index = self._config.get("index", {}) if isinstance(self._config.get("index", {}), dict) else {}
        k = int(limit or cfg_index.get("top_k", 5) or 5)
        min_score = float(cfg_index.get("min_score", 0.0) or 0.0)
        filters = _filters_from_window(time_window, app_filter)
        spans_by_id = {span.get("state_id"): span for span in store.get_spans(
            session_id=filters.get("session_id"),
            start_ms=filters.get("start_ms"),
            end_ms=filters.get("end_ms"),
            app=filters.get("app"),
        )}

        def _search_with_vector(vec: list[float], *, model_filter: str | None, exclude_model: str | None, tier_label: str) -> list[dict[str, Any]]:
            hits = []
            if self._vector_index is not None and hasattr(self._vector_index, "query"):
                try:
                    raw_hits = self._vector_index.query(vec, filters=filters, k=k)
                    for hit in raw_hits:
                        if isinstance(hit, dict):
                            score_val = hit.get("score")
                            hits.append({"state_id": hit.get("state_id"), "score": float(score_val or 0.0)})
                        else:
                            score_val = getattr(hit, "score", 0.0)
                            hits.append({"state_id": getattr(hit, "state_id", None), "score": float(score_val or 0.0)})
                    trace.append({"tier": tier_label, "count": len(hits)})
                except Exception:
                    hits = []
                    trace.append({"tier": f"{tier_label}_ERROR"})
            if not hits:
                spans = store.get_spans(
                    session_id=filters.get("session_id"),
                    start_ms=filters.get("start_ms"),
                    end_ms=filters.get("end_ms"),
                    app=filters.get("app"),
                    limit=filters.get("limit"),
                )
                trace.append({"tier": f"{tier_label}_LINEAR", "count": len(spans)})
                for span in spans:
                    z_vec = _unpack_embedding(span.get("z_embedding", {}))
                    score = _cosine(vec, z_vec)
                    hits.append({"state_id": span.get("state_id"), "score": float(score)})
            def _score(item: dict[str, Any]) -> float:
                return float(item.get("score") or 0.0)

            hits = [hit for hit in hits if _score(hit) >= min_score and hit.get("state_id")]
            hits.sort(key=lambda h: (-_score(h), str(h.get("state_id"))))
            hits = hits[: max(1, k)]

            edge_evidence: dict[str, list[dict[str, Any]]] = {}
            try:
                hit_ids = [str(hit.get("state_id")) for hit in hits if hit.get("state_id")]
                if hit_ids:
                    edges = store.get_edges_for_states(hit_ids)
                    edge_evidence = _edge_evidence_map(edges)
            except Exception:
                edge_evidence = {}

            results: list[dict[str, Any]] = []
            for hit in hits:
                span_record: dict[str, Any] | None = spans_by_id.get(hit["state_id"])
                if not isinstance(span_record, dict):
                    continue
                if not self._policy_gate.app_allowed(span_record.get("summary_features", {}).get("app"), policy):
                    continue
                prov = span_record.get("provenance", {}) if isinstance(span_record.get("provenance"), dict) else {}
                model_ver = str(prov.get("model_version") or "")
                if model_filter and model_ver and model_ver != model_filter:
                    continue
                if exclude_model and model_ver and model_ver == exclude_model:
                    continue
                merged_evidence = _merge_evidence(
                    span_record.get("evidence", []),
                    edge_evidence.get(str(span_record.get("state_id")), []),
                )
                results.append(
                    {
                        "state_id": span_record.get("state_id"),
                        "score": _score(hit),
                        "ts_start_ms": int(span_record.get("ts_start_ms", 0) or 0),
                        "ts_end_ms": int(span_record.get("ts_end_ms", 0) or 0),
                        "summary_features": span_record.get("summary_features", {}),
                        "evidence": merged_evidence,
                        "provenance": span_record.get("provenance", {}),
                    }
                )
            return results

        results = _search_with_vector(query_vec, model_filter=self._model_version, exclude_model=None, tier_label="VECTOR_INDEX")
        if not results and self._jepa_model is not None:
            training_cfg = self._config.get("training", {}) if isinstance(self._config.get("training", {}), dict) else {}
            if bool(training_cfg.get("fallback_enabled", True)):
                fallback_vec = self._embed_query(query_text, use_jepa=False)
                if fallback_vec:
                    trace.append({"tier": "MODEL_VERSION_FALLBACK"})
                    results = _search_with_vector(
                        fallback_vec,
                        model_filter=None,
                        exclude_model=self._model_version,
                        tier_label="VECTOR_INDEX_FALLBACK",
                    )
        self._last_trace = trace
        return results

    def _init_embedder(self) -> None:
        embedder = None
        try:
            embedder = self.context.get_capability("embedder.text")
        except Exception:
            embedder = None
        if embedder is None:
            embedder = LocalEmbedder(self._config.get("embedder_model"))
        self._embedder = embedder
        identity = {}
        try:
            if hasattr(embedder, "embed"):
                sample = embedder.embed("state_query_probe")
                if isinstance(sample, list):
                    identity["dims"] = len(sample)
            if hasattr(embedder, "identity"):
                identity.update(embedder.identity())
        except Exception:
            pass
        self._embedder_identity = identity
        try:
            version = identity.get("bundle_version") or identity.get("version") or None
            if version is not None:
                self._model_version = str(version)
        except Exception:
            self._model_version = None

    def _maybe_load_jepa_model(self) -> None:
        features = self._config.get("features", {}) if isinstance(self._config.get("features", {}), dict) else {}
        if not bool(features.get("training_enabled", False)):
            return
        try:
            from .jepa_training import JEPATraining

            trainer = JEPATraining(f"{self.plugin_id}.loader", self.context)
            payload = trainer.load_latest(expected_config_hash=self._config_hash)
        except Exception:
            payload = None
        if not isinstance(payload, dict) or not payload:
            return
        try:
            model = JEPAModel.from_payload(payload)
        except Exception:
            return
        if not model.encoder or model.input_dim <= 0:
            return
        self._jepa_model = model
        self._model_version = model.model_version

    def _embed_query(self, text: str, *, use_jepa: bool = True) -> list[float]:
        embedder = self._embedder
        if embedder is None:
            return []
        try:
            vector = embedder.embed(text)
            if isinstance(vector, dict):
                vector = vector.get("vector", [])
            if isinstance(vector, list):
                vec = [float(v) for v in vector]
            else:
                vec = []
        except Exception:
            vec = []
        if not vec:
            return []
        vec = _normalize(vec)
        if use_jepa and self._jepa_model is not None:
            input_dim = self._jepa_model.input_dim
            if len(vec) != input_dim:
                vec = _project_vector(vec, out_dim=input_dim, seed=self._config_hash)
            embedded = self._jepa_model.embed(vec, out_dim=768)
            return _normalize(embedded)
        if len(vec) != 768:
            vec = _project_vector(vec, out_dim=768, seed=self._config_hash)
        return _normalize(vec)


def _resolve_store(context: PluginContext) -> StateTapeStore | None:
    try:
        store = context.get_capability("storage.state_tape")
    except Exception:
        store = None
    return store


def _resolve_vector_index(context: PluginContext) -> Any | None:
    try:
        return context.get_capability("state.vector_index")
    except Exception:
        return None


def _filters_from_window(time_window: dict[str, Any] | None, app: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if time_window:
        filters["start_ms"] = _parse_ms(time_window.get("start"))
        filters["end_ms"] = _parse_ms(time_window.get("end"))
    if app:
        filters["app"] = app
    return filters


def _parse_ms(value: Any) -> int | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(text).timestamp() * 1000.0)
    except Exception:
        return None


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _project_vector(vec: list[float], *, out_dim: int, seed: str) -> list[float]:
    if not vec:
        return [0.0] * out_dim
    in_dim = len(vec)
    scale = 1.0 / math.sqrt(float(in_dim) or 1.0)
    seed_bytes = hashlib.sha256(seed.encode("utf-8")).digest()
    out: list[float] = []
    for i in range(out_dim):
        acc = 0.0
        for j in range(in_dim):
            h = hashlib.sha256(seed_bytes + i.to_bytes(2, "big") + j.to_bytes(2, "big")).digest()
            weight = 1.0 if (h[0] & 1) == 1 else -1.0
            acc += weight * vec[j]
        out.append(acc * scale)
    return out


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


def _edge_evidence_map(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        evidence = edge.get("evidence", [])
        if not isinstance(evidence, list):
            continue
        for state_id in (edge.get("from_state_id"), edge.get("to_state_id")):
            if not state_id:
                continue
            mapping.setdefault(str(state_id), []).extend([e for e in evidence if isinstance(e, dict)])
    return mapping


def _merge_evidence(
    span_evidence: Any,
    edge_evidence: Any,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(span_evidence, list):
        items.extend([e for e in span_evidence if isinstance(e, dict)])
    if isinstance(edge_evidence, list):
        items.extend([e for e in edge_evidence if isinstance(e, dict)])
    deduped: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}
    for item in items:
        key = (
            item.get("media_id"),
            int(item.get("ts_start_ms", 0) or 0),
            int(item.get("ts_end_ms", 0) or 0),
            int(item.get("frame_index", 0) or 0),
        )
        if key in deduped:
            continue
        deduped[key] = item
    merged = list(deduped.values())
    merged.sort(key=lambda r: (int(r.get("ts_start_ms", 0)), str(r.get("media_id", ""))))
    return merged
