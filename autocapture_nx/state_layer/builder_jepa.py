"""Baseline JEPA-like StateBuilderPlugin (deterministic, no training)."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from autocapture.indexing.vector import LocalEmbedder
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

from .contracts import validate_state_edge, validate_state_span
from .ids import compute_cache_key, compute_config_hash, deterministic_id_from_parts
from .jepa_model import JEPAModel


class JEPAStateBuilder(PluginBase):
    """Deterministic state builder for StateSpan + StateEdge."""

    VERSION = "1.0.0"

    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._cfg = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}
        self._builder_cfg = self._cfg.get("builder", {}) if isinstance(self._cfg.get("builder", {}), dict) else {}
        self._embedder = None
        self._embedder_identity: dict[str, Any] = {}
        self._model_id = "hash"
        self._model_version = "v1"
        self._config_hash = compute_config_hash(self._builder_cfg)
        self._jepa_model: JEPAModel | None = None
        self._init_embedder()
        self._maybe_load_jepa_model()

    def capabilities(self) -> dict[str, Any]:
        return {"state.builder": self}

    def _init_embedder(self) -> None:
        embedder = None
        try:
            embedder = self.context.get_capability("embedder.text")
        except Exception:
            embedder = None
        if embedder is None:
            embedder = LocalEmbedder(self._cfg.get("embedder_model"))
        self._embedder = embedder
        identity = {}
        try:
            if hasattr(embedder, "embed"):
                sample = embedder.embed("state_layer_identity_probe")
                if isinstance(sample, list):
                    identity["dims"] = len(sample)
            if hasattr(embedder, "identity"):
                identity.update(embedder.identity())
        except Exception:
            pass
        self._embedder_identity = identity
        model_id = str(identity.get("backend", "hash"))
        if identity.get("model_name"):
            model_id = f"{model_id}:{identity.get('model_name')}"
        if identity.get("bundle_id"):
            model_id = f"{model_id}:{identity.get('bundle_id')}"
        self._model_id = model_id
        self._model_version = str(identity.get("bundle_version") or identity.get("version") or "v1")

    def model_version(self) -> str:
        return str(self._model_version)

    def config_hash(self) -> str:
        return str(self._config_hash)

    def _maybe_load_jepa_model(self) -> None:
        features = self._cfg.get("features", {}) if isinstance(self._cfg.get("features", {}), dict) else {}
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
        self._model_id = f"jepa:{model.model_version}"
        self._model_version = model.model_version

    def process(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Process an ExtractBatch -> StateTapeBatch.

        Expected batch: {"session_id": str, "states": [derived_sst_state_record, ...]}.
        """
        session_id = str(batch.get("session_id") or "")
        states = batch.get("states", [])
        if not isinstance(states, list):
            return {"spans": [], "edges": []}
        cleaned = [s for s in states if isinstance(s, dict)]
        cleaned.sort(key=lambda s: int(_state_ts_ms(s) or 0))
        spans = self._build_spans(session_id, cleaned)
        edges = self._build_edges(spans)
        for span in spans:
            validate_state_span(span)
        for edge in edges:
            validate_state_edge(edge)
        return {"spans": spans, "edges": edges}

    def _window_mode(self) -> str:
        return str(self._builder_cfg.get("windowing_mode", "fixed_duration") or "fixed_duration")

    def _window_ms(self) -> int:
        return int(self._builder_cfg.get("window_ms", 5000) or 5000)

    def _max_evidence_refs(self) -> int:
        return int(self._builder_cfg.get("max_evidence_refs", 3) or 3)

    def _build_spans(self, session_id: str, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not states:
            return []
        mode = self._window_mode()
        window_ms = max(1000, self._window_ms())
        windows: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_start = None
        current_app = None
        for state in states:
            ts_ms = _state_ts_ms(state)
            if ts_ms is None:
                continue
            app_hint = _state_app_hint(state)
            if not current:
                current = [state]
                current_start = ts_ms
                current_app = app_hint
                continue
            if mode == "heuristic_app_window_change" and app_hint and current_app and app_hint != current_app:
                windows.append(current)
                current = [state]
                current_start = ts_ms
                current_app = app_hint
                continue
            if current_start is not None and ts_ms - current_start >= window_ms:
                windows.append(current)
                current = [state]
                current_start = ts_ms
                current_app = app_hint
                continue
            current.append(state)
        if current:
            windows.append(current)
        spans: list[dict[str, Any]] = []
        for window in windows:
            span = self._span_from_window(session_id, window)
            if span is None:
                continue
            spans.append(span)
        spans.sort(key=lambda s: (s.get("ts_start_ms", 0), s.get("state_id", "")))
        return spans

    def _span_from_window(self, session_id: str, window: list[dict[str, Any]]) -> dict[str, Any] | None:
        ts_start = min(int(_state_ts_ms(s) or 0) for s in window)
        ts_end = max(int(_state_ts_ms(s) or 0) for s in window)
        inputs = [str(s.get("record_id") or s.get("artifact_id") or "") for s in window]
        inputs = [item for item in inputs if item]
        inputs.sort()
        cache_key = compute_cache_key(self.plugin_id, self.VERSION, self._model_version, self._config_hash, inputs)
        parts = {
            "kind": "state_span",
            "session_id": session_id,
            "ts_start_ms": ts_start,
            "ts_end_ms": ts_end,
            "cache_key": cache_key,
        }
        state_id = deterministic_id_from_parts(parts)
        base_vec = self._pool_window_embeddings(window)
        if self._jepa_model is not None:
            z_vec = self._jepa_model.embed(base_vec, out_dim=768)
        else:
            z_vec = base_vec
        z_emb = _pack_embedding(z_vec, dim=768)
        evidence_refs = self._evidence_for_window(window)
        if not evidence_refs:
            if hasattr(self.context, "logger"):
                try:
                    self.context.logger("state.builder.missing_evidence")
                except Exception:
                    pass
            return None
        app_hint = _state_app_hint(window[0])
        window_title_hash = _hash_text(app_hint or "")[:16]
        top_entities = _top_entities(window)
        provenance = {
            "producer_plugin_id": self.plugin_id,
            "producer_plugin_version": self.VERSION,
            "model_id": self._model_id,
            "model_version": self._model_version,
            "config_hash": self._config_hash,
            "input_artifact_ids": inputs,
            "created_ts_ms": int(ts_end),
        }
        return {
            "state_id": state_id,
            "session_id": session_id,
            "ts_start_ms": int(ts_start),
            "ts_end_ms": int(ts_end),
            "z_embedding": z_emb,
            "summary_features": {
                "app": app_hint or "",
                "window_title_hash": window_title_hash,
                "top_entities": top_entities,
            },
            "evidence": evidence_refs,
            "provenance": provenance,
        }

    def _build_edges(self, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for idx in range(1, len(spans)):
            prev = spans[idx - 1]
            curr = spans[idx]
            z_prev = _unpack_embedding(prev.get("z_embedding", {}))
            z_curr = _unpack_embedding(curr.get("z_embedding", {}))
            delta = [c - p for p, c in zip(z_prev, z_curr)]
            pred_error = 1.0 - _cosine(z_prev, z_curr)
            parts = {
                "kind": "state_edge",
                "from": prev.get("state_id"),
                "to": curr.get("state_id"),
                "config_hash": self._config_hash,
                "model_version": self._model_version,
            }
            edge_id = deterministic_id_from_parts(parts)
            evidence = curr.get("evidence", []) if isinstance(curr.get("evidence"), list) else []
            provenance = {
                "producer_plugin_id": self.plugin_id,
                "producer_plugin_version": self.VERSION,
                "model_id": self._model_id,
                "model_version": self._model_version,
                "config_hash": self._config_hash,
                "input_artifact_ids": [prev.get("state_id", ""), curr.get("state_id", "")],
                "created_ts_ms": int(curr.get("ts_end_ms", 0)),
            }
            edge = {
                "edge_id": edge_id,
                "from_state_id": prev.get("state_id"),
                "to_state_id": curr.get("state_id"),
                "delta_embedding": _pack_embedding(delta, dim=768),
                "pred_error": float(pred_error),
                "evidence": list(evidence),
                "provenance": provenance,
            }
            edges.append(edge)
        return edges

    def _pool_window_embeddings(self, window: list[dict[str, Any]]) -> list[float]:
        vectors = []
        for state in window:
            vectors.append(self._state_embedding(state))
        if not vectors:
            return [0.0] * 768
        dim = len(vectors[0])
        agg = [0.0] * dim
        for vec in vectors:
            for idx, val in enumerate(vec):
                agg[idx] += val
        denom = float(len(vectors)) or 1.0
        agg = [val / denom for val in agg]
        return _project_vector(agg, out_dim=768, seed=self._config_hash)

    def _state_embedding(self, state_record: dict[str, Any]) -> list[float]:
        state = _screen_state(state_record)
        text = _state_text(state)
        text_vec = self._text_embedding(text)
        base_dim = len(text_vec) if text_vec else int(self._embedder_identity.get("dims") or 384)
        if base_dim <= 0:
            base_dim = 384
        vision_vec = _hash_to_vector(_state_vision_seed(state), base_dim)
        layout_vec = _hash_to_vector(_state_layout_seed(state), base_dim)
        input_vec = _hash_to_vector(_state_input_seed(state), base_dim)
        weights = {
            "text": float(self._builder_cfg.get("text_weight", 1.0)),
            "vision": float(self._builder_cfg.get("vision_weight", 0.6)),
            "layout": float(self._builder_cfg.get("layout_weight", 0.4)),
            "input": float(self._builder_cfg.get("input_weight", 0.2)),
        }
        merged = [0.0] * base_dim
        for idx in range(base_dim):
            merged[idx] = (
                weights["text"] * _safe_val(text_vec, idx)
                + weights["vision"] * _safe_val(vision_vec, idx)
                + weights["layout"] * _safe_val(layout_vec, idx)
                + weights["input"] * _safe_val(input_vec, idx)
            )
        return _normalize(merged)

    def _text_embedding(self, text: str) -> list[float]:
        if not text:
            return []
        embedder = self._embedder
        if embedder is None:
            return []
        try:
            vector = embedder.embed(text)
            if isinstance(vector, dict):
                vector = vector.get("vector", [])
            if isinstance(vector, list):
                return [float(v) for v in vector]
        except Exception:
            return []
        return []

    def _evidence_for_window(self, window: list[dict[str, Any]]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for record in window:
            ref = _state_evidence_ref(record)
            if ref is not None:
                refs.append(ref)
        refs.sort(key=lambda r: (int(r.get("ts_start_ms", 0)), str(r.get("media_id", ""))))
        max_refs = self._max_evidence_refs()
        if max_refs > 0:
            refs = refs[:max_refs]
        return refs


def _state_ts_ms(state_record: dict[str, Any]) -> int | None:
    state = _screen_state(state_record)
    ts = state.get("ts_ms") if isinstance(state, dict) else None
    if ts is None:
        return None
    try:
        return int(ts)
    except Exception:
        return None


def _screen_state(state_record: dict[str, Any]) -> dict[str, Any]:
    screen_state = state_record.get("screen_state")
    if isinstance(screen_state, dict):
        return screen_state
    state = state_record.get("state")
    if isinstance(state, dict):
        return state
    return state_record


def _state_text(state: dict[str, Any]) -> str:
    tokens = state.get("tokens", []) if isinstance(state.get("tokens"), (list, tuple)) else []
    if not tokens:
        return ""
    tokens_sorted = sorted(tokens, key=lambda t: (t.get("bbox", (0, 0, 0, 0))[1], t.get("bbox", (0, 0, 0, 0))[0], t.get("token_id", "")))
    parts = []
    for token in tokens_sorted:
        text = str(token.get("norm_text") or token.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _state_app_hint(state_record: dict[str, Any]) -> str | None:
    state = _screen_state(state_record)
    apps = state.get("visible_apps") if isinstance(state.get("visible_apps"), (list, tuple)) else []
    if apps:
        return str(apps[0])
    return None


def _state_vision_seed(state: dict[str, Any]) -> str:
    return str(state.get("image_sha256") or state.get("phash") or "")


def _state_layout_seed(state: dict[str, Any]) -> str:
    element_graph_raw = state.get("element_graph")
    element_graph = element_graph_raw if isinstance(element_graph_raw, dict) else {}
    elements_raw = element_graph.get("elements")
    elements = elements_raw if isinstance(elements_raw, (list, tuple)) else []
    types = sorted({str(el.get("type", "")) for el in elements if isinstance(el, dict) and el.get("type")})
    return "|".join(types)


def _state_input_seed(state: dict[str, Any]) -> str:
    focus = state.get("focus_element_id") or ""
    return str(focus)


def _state_evidence_ref(state_record: dict[str, Any]) -> dict[str, Any] | None:
    state = _screen_state(state_record)
    media_id = state.get("frame_id")
    if not media_id:
        return None
    ts_ms = int(state.get("ts_ms", 0) or 0)
    width = int(state.get("width", 0) or 0)
    height = int(state.get("height", 0) or 0)
    sha256 = str(state.get("image_sha256") or "")
    return {
        "media_id": str(media_id),
        "ts_start_ms": ts_ms,
        "ts_end_ms": ts_ms,
        "frame_index": int(state.get("frame_index", 0) or 0),
        "bbox_xywh": [0, 0, width, height],
        "text_span": {"start": 0, "end": 0},
        "sha256": sha256,
        "redaction_applied": False,
    }


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_to_vector(seed: str, dim: int) -> list[float]:
    if dim <= 0:
        return []
    base = hashlib.sha256(seed.encode("utf-8")).digest()
    vec: list[float] = []
    counter = 0
    while len(vec) < dim:
        digest = hashlib.sha256(base + counter.to_bytes(4, "big")).digest()
        for idx in range(0, len(digest), 2):
            if len(vec) >= dim:
                break
            chunk = digest[idx : idx + 2]
            val = int.from_bytes(chunk, "big") / 65535.0
            vec.append((val * 2.0) - 1.0)
        counter += 1
    return _normalize(vec)


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


def _pack_embedding(vec: list[float], *, dim: int) -> dict[str, Any]:
    if not vec:
        vec = [0.0] * dim
    if len(vec) != dim:
        vec = _project_vector(vec, out_dim=dim, seed="pad")
    blob = b"".join(_float_to_f16(val) for val in vec)
    return {"dim": int(dim), "dtype": "f16", "blob": _b64(blob)}


def _unpack_embedding(embedding: dict[str, Any]) -> list[float]:
    if not isinstance(embedding, dict):
        return []
    blob = embedding.get("blob")
    if isinstance(blob, str):
        blob = _b64decode(blob)
    if not isinstance(blob, (bytes, bytearray)):
        return []
    data = bytes(blob)
    if not data:
        return []
    vec = []
    for idx in range(0, len(data), 2):
        vec.append(_f16_to_float(data[idx : idx + 2]))
    return vec


def _float_to_f16(value: float) -> bytes:
    import struct

    try:
        return struct.pack("e", float(value))
    except Exception:
        return struct.pack("e", 0.0)


def _f16_to_float(blob: bytes) -> float:
    import struct

    if len(blob) != 2:
        return 0.0
    try:
        return float(struct.unpack("e", blob)[0])
    except Exception:
        return 0.0


def _b64(blob: bytes) -> str:
    import base64

    return base64.b64encode(blob).decode("ascii")


def _b64decode(text: str) -> bytes:
    import base64

    return base64.b64decode(text.encode("ascii"))


def _safe_val(vec: list[float], idx: int) -> float:
    if idx < len(vec):
        return vec[idx]
    return 0.0


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _top_entities(window: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for record in window:
        state = _screen_state(record)
        tokens = state.get("tokens", []) if isinstance(state.get("tokens"), (list, tuple)) else []
        for token in tokens:
            text = str(token.get("norm_text") or token.get("text") or "").strip().lower()
            if not text or text.isdigit():
                continue
            counts[text] = counts.get(text, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [text for text, _count in items[:5]]
