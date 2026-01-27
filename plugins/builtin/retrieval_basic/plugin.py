"""Basic retrieval strategy plugin with deterministic tie-breaks."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Any

from autocapture.indexing.factory import build_indexes
from autocapture.retrieval.fusion import rrf_fusion
from autocapture.retrieval.rerank import Reranker
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class RetrievalStrategy(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._config = context.config if isinstance(context.config, dict) else {}
        retrieval_cfg = self._config.get("retrieval", {}) if isinstance(self._config, dict) else {}
        self._fast_threshold = int(retrieval_cfg.get("fast_threshold", 3))
        self._fusion_threshold = int(retrieval_cfg.get("fusion_threshold", 5))
        self._lexical = None
        self._vector = None
        self._indexes_ready = False
        self._reranker = Reranker()
        self._last_trace: list[dict[str, Any]] = []
        self._index_meta: dict[str, Any] = {}

    def capabilities(self) -> dict[str, Any]:
        return {"retrieval.strategy": self}

    def trace(self) -> list[dict[str, Any]]:
        return list(self._last_trace)

    def search(self, query: str, time_window: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        store = self.context.get_capability("storage.metadata")
        if store is None:
            return []
        query_text = str(query or "").strip()
        if not query_text:
            return []
        trace: list[dict[str, Any]] = []
        window_events, input_summaries, cursor_samples = _collect_timelines(store)
        candidate_ids = _time_window_candidates(store, time_window, self._config)
        if candidate_ids is not None:
            trace.append(
                {
                    "tier": "TIME_WINDOW",
                    "candidates": int(len(candidate_ids)),
                    "start": (time_window or {}).get("start"),
                    "end": (time_window or {}).get("end"),
                }
            )
        results, trace = self._search_indexed(store, query_text, time_window, trace, candidate_ids)
        if not results:
            results = _scan_metadata(store, query_text.lower(), time_window, candidate_ids)
        results.sort(
            key=lambda r: (
                -float(r.get("score", 0.0)),
                -(_ts_key(r.get("ts_utc")) or 0.0),
                str(r.get("record_type", "")),
                str(r.get("record_id", "")),
                str(r.get("derived_id", "")),
            )
        )
        _attach_timelines(results, store, window_events, input_summaries, cursor_samples)
        self._last_trace = trace
        return results

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._indexes_ready = True
        if not self._config:
            return
        logger = self.context.logger if callable(getattr(self.context, "logger", None)) else None
        self._lexical, self._vector = build_indexes(self._config, logger=logger)
        self._index_meta = {}
        if self._lexical is not None and hasattr(self._lexical, "identity"):
            try:
                self._index_meta["lexical"] = self._lexical.identity()
            except Exception:
                self._index_meta["lexical"] = {"backend": "unknown"}
        if self._vector is not None and hasattr(self._vector, "identity"):
            try:
                self._index_meta["vector"] = self._vector.identity()
            except Exception:
                self._index_meta["vector"] = {"backend": "unknown"}

    def _search_indexed(
        self,
        store: Any,
        query: str,
        time_window: dict[str, Any] | None,
        trace: list[dict[str, Any]],
        candidate_ids: set[str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self._ensure_indexes()
        if self._lexical is None and self._vector is None:
            return [], trace
        retrieval_cfg = self._config.get("retrieval", {}) if isinstance(self._config, dict) else {}
        limit = int(retrieval_cfg.get("limit", 25))
        vector_limit = int(retrieval_cfg.get("vector_limit", limit))
        lexical_hits: list[dict[str, Any]] = []
        vector_hits: list[dict[str, Any]] = []
        if self._lexical is not None:
            try:
                if self._lexical.count() > 0:
                    lexical_hits = self._lexical.query(query, limit=limit)
            except Exception:
                lexical_hits = []
        if candidate_ids is not None:
            lexical_hits = [hit for hit in lexical_hits if hit.get("doc_id") in candidate_ids]
        trace.append({"tier": "LEXICAL", "result_count": len(lexical_hits), "index": self._index_meta.get("lexical")})
        if self._vector is not None:
            vector_ok, reason = _allow_vector(self.context, self._config)
            if vector_ok:
                try:
                    if not hasattr(self._vector, "count") or self._vector.count() > 0:
                        vector_hits = [{"doc_id": hit.doc_id, "score": hit.score} for hit in self._vector.query(query, limit=vector_limit)]
                except Exception:
                    vector_hits = []
                if candidate_ids is not None:
                    vector_hits = [hit for hit in vector_hits if hit.get("doc_id") in candidate_ids]
                trace.append({"tier": "VECTOR", "result_count": len(vector_hits), "index": self._index_meta.get("vector")})
            else:
                trace.append({"tier": "VECTOR_SKIPPED", "reason": reason})
        if not lexical_hits and not vector_hits:
            return [], trace

        snippet_map = {hit.get("doc_id"): hit.get("snippet") for hit in lexical_hits if hit.get("doc_id")}
        if len(lexical_hits) >= self._fast_threshold:
            candidates = lexical_hits
            trace.append({"tier": "FAST", "result_count": len(candidates)})
        else:
            rankings = []
            if lexical_hits:
                rankings.append(lexical_hits)
            if vector_hits:
                rankings.append(vector_hits)
            if len(rankings) >= 2:
                fused = rrf_fusion(rankings)
            elif rankings:
                fused = rankings[0]
            else:
                fused = []
            if len(fused) >= self._fusion_threshold:
                candidates = fused
                trace.append({"tier": "FUSION", "result_count": len(candidates)})
            else:
                candidates = self._rerank_candidates(query, fused, store)
                trace.append({"tier": "RERANK", "result_count": len(candidates)})
        for item in candidates:
            doc_id = item.get("doc_id")
            if doc_id and doc_id in snippet_map and "snippet" not in item:
                item["snippet"] = snippet_map[doc_id]
        return _map_candidates(candidates, store, time_window), trace

    def _rerank_candidates(self, query: str, candidates: list[dict[str, Any]], store: Any) -> list[dict[str, Any]]:
        if not candidates:
            return []
        docs: list[dict[str, Any]] = []
        for item in candidates:
            doc_id = item.get("doc_id") or item.get("record_id")
            if not doc_id:
                continue
            record = store.get(doc_id, {})
            docs.append({**item, "doc_id": doc_id, "text": record.get("text", "")})
        return self._reranker.rerank(query, docs)


def create_plugin(plugin_id: str, context: PluginContext) -> RetrievalStrategy:
    return RetrievalStrategy(plugin_id, context)


def _collect_timelines(
    store: Any,
) -> tuple[list[tuple[float, str, dict[str, Any]]], list[tuple[float, float, str]], list[tuple[float, str]]]:
    window_events: list[tuple[float, str, dict[str, Any]]] = []
    input_summaries: list[tuple[float, float, str]] = []
    cursor_samples: list[tuple[float, str]] = []
    for record_id in getattr(store, "keys", lambda: [])():
        record = store.get(record_id, {})
        record_type = str(record.get("record_type", ""))
        if record_type == "evidence.window.meta":
            ts_val = _ts_key(record.get("ts_utc"))
            if ts_val is not None:
                window_events.append((ts_val, record_id, record))
        elif record_type == "derived.input.summary":
            start_ts = _ts_key(record.get("start_ts_utc") or record.get("ts_start_utc"))
            end_ts = _ts_key(record.get("end_ts_utc") or record.get("ts_end_utc"))
            if start_ts is not None and end_ts is not None:
                input_summaries.append((start_ts, end_ts, record_id))
        elif record_type == "derived.cursor.sample":
            ts_val = _ts_key(record.get("ts_utc"))
            if ts_val is not None:
                cursor_samples.append((ts_val, record_id))
    return window_events, input_summaries, cursor_samples


def _within_window(ts: str | None, time_window: dict[str, Any] | None) -> bool:
    if not time_window:
        return True
    ts_val = _ts_key(ts)
    if ts_val is None:
        return False
    start = _ts_key(time_window.get("start"))
    end = _ts_key(time_window.get("end"))
    if start is not None and ts_val < start:
        return False
    if end is not None and ts_val > end:
        return False
    return True


def _scan_metadata(
    store: Any,
    query_lower: str,
    time_window: dict[str, Any] | None,
    candidate_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    record_ids = list(getattr(store, "keys", lambda: [])())
    if candidate_ids is not None:
        record_ids = [rid for rid in record_ids if rid in candidate_ids]
    for record_id in record_ids:
        record = store.get(record_id, {})
        text = str(record.get("text", "")).lower()
        if not query_lower or query_lower not in text:
            continue
        ts = record.get("ts_utc")
        if not _within_window(ts, time_window):
            continue
        source_id = record.get("source_id") or record_id
        derived_id = record_id if source_id != record_id else None
        result = {"record_id": source_id, "score": 1.0, "ts_utc": ts}
        if derived_id:
            result["derived_id"] = derived_id
        results.append(result)
    return results


def _map_candidates(
    candidates: list[dict[str, Any]],
    store: Any,
    time_window: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        doc_id = item.get("doc_id") or item.get("record_id")
        if not doc_id:
            continue
        record = store.get(doc_id, {})
        if not record:
            continue
        source_id = record.get("source_id") or doc_id
        source_record = record if source_id == doc_id else store.get(source_id, {})
        ts = record.get("ts_utc") or source_record.get("ts_utc")
        if not _within_window(ts, time_window):
            continue
        score = float(item.get("score", 0.0))
        record_type = str(source_record.get("record_type", ""))
        result = {"record_id": source_id, "score": score, "ts_utc": ts, "record_type": record_type}
        if source_id != doc_id:
            result["derived_id"] = doc_id
        snippet = item.get("snippet")
        if snippet:
            result["snippet"] = snippet
        existing = mapped.get(source_id)
        if existing is None:
            mapped[source_id] = result
        else:
            existing_score = float(existing.get("score", 0.0))
            if score > existing_score:
                mapped[source_id] = result
            elif score == existing_score and result.get("derived_id") and not existing.get("derived_id"):
                mapped[source_id] = result
    return list(mapped.values())


def _ts_key(ts: str | None) -> float | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


def _attach_timelines(
    results: list[dict[str, Any]],
    store: Any,
    window_events: list[tuple[float, str, dict[str, Any]]],
    input_summaries: list[tuple[float, float, str]],
    cursor_samples: list[tuple[float, str]],
) -> None:
    if not results:
        return
    if window_events:
        window_events.sort(key=lambda item: item[0])
    if input_summaries:
        input_summaries.sort(key=lambda item: item[0])
    if cursor_samples:
        cursor_samples.sort(key=lambda item: item[0])
    window_times = [ts for ts, _rid, _record in window_events]
    cursor_times = [ts for ts, _rid in cursor_samples]
    for result in results:
        record_id = result.get("record_id")
        if not record_id:
            continue
        record = store.get(record_id, {})
        record_type = str(record.get("record_type", ""))
        if not record_type.startswith("evidence.capture."):
            continue
        start_ts = _ts_key(record.get("ts_start_utc") or record.get("ts_utc"))
        end_ts = _ts_key(record.get("ts_end_utc") or record.get("ts_utc"))
        if start_ts is None:
            continue
        if window_events:
            idx = bisect_right(window_times, start_ts) - 1
            if idx >= 0:
                _ts_val, window_id, window_record = window_events[idx]
                window_ref = {"record_id": window_id, "ts_utc": window_record.get("ts_utc")}
                if window_record.get("window"):
                    window_ref["window"] = window_record.get("window")
                result["window_ref"] = window_ref
            if end_ts is not None:
                left = bisect_left(window_times, start_ts)
                right = bisect_right(window_times, end_ts)
                if right > left:
                    result["window_timeline"] = [window_events[i][1] for i in range(left, right)]
        if input_summaries and end_ts is not None:
            input_refs: list[str] = []
            for start, end, input_id in input_summaries:
                if end < start_ts or start > end_ts:
                    continue
                input_refs.append(input_id)
            if input_refs:
                result["input_refs"] = input_refs
        if cursor_samples and end_ts is not None:
            left = bisect_left(cursor_times, start_ts)
            right = bisect_right(cursor_times, end_ts)
            if right > left:
                result["cursor_refs"] = [cursor_samples[i][1] for i in range(left, right)]


def _time_window_candidates(
    store: Any,
    time_window: dict[str, Any] | None,
    config: dict[str, Any],
) -> set[str] | None:
    if not time_window:
        return None
    start_ts = time_window.get("start")
    end_ts = time_window.get("end")
    if not start_ts and not end_ts:
        return None
    retrieval_cfg = config.get("retrieval", {}) if isinstance(config, dict) else {}
    limit = retrieval_cfg.get("window_limit")
    try:
        limit_val = int(limit) if limit is not None else None
    except Exception:
        limit_val = None
    if hasattr(store, "query_time_window"):
        try:
            ids = store.query_time_window(start_ts, end_ts, limit=limit_val)
            return set(ids)
        except Exception:
            return None
    return None


def _allow_vector(context: PluginContext, config: dict[str, Any]) -> tuple[bool, str]:
    retrieval_cfg = config.get("retrieval", {}) if isinstance(config, dict) else {}
    if isinstance(retrieval_cfg, dict) and not bool(retrieval_cfg.get("vector_enabled", True)):
        return False, "disabled"
    require_idle = bool(retrieval_cfg.get("vector_requires_idle", True))
    idle_threshold = retrieval_cfg.get("vector_idle_seconds")
    if idle_threshold is None:
        idle_threshold = config.get("runtime", {}).get("idle_window_s", 45)
    try:
        idle_threshold = float(idle_threshold)
    except Exception:
        idle_threshold = 45.0
    if not require_idle:
        return True, "enabled"
    tracker = None
    try:
        tracker = context.get_capability("tracking.input")
    except Exception:
        tracker = None
    if tracker is None:
        assume_idle = bool(config.get("runtime", {}).get("activity", {}).get("assume_idle_when_missing", False))
        return (assume_idle, "missing_tracker" if not assume_idle else "assumed_idle")
    try:
        idle_seconds = float(tracker.idle_seconds())
    except Exception:
        idle_seconds = 0.0
    if idle_seconds < idle_threshold:
        return False, "active"
    return True, "idle"
