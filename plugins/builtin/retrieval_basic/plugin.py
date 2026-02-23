"""Basic retrieval strategy plugin with deterministic tie-breaks."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
import json
import os
import re
import time
from typing import Any

from autocapture.indexing.factory import build_indexes
from autocapture.retrieval.fusion import rrf_fusion
from autocapture.retrieval.rerank import Reranker
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.kernel.ids import decode_record_id_component
from autocapture_nx.kernel.providers import capability_providers


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
        self._rerank_fallback = Reranker()
        self._rerankers: list[tuple[str, Any]] = []
        self._last_trace: list[dict[str, Any]] = []
        self._index_meta: dict[str, Any] = {}
        self._latency_hist_edges_ms: tuple[float, ...] = (5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0)
        self._latency_hist_counts: dict[str, int] = {f"le_{int(edge)}ms": 0 for edge in self._latency_hist_edges_ms}
        self._latency_hist_counts["gt_5000ms"] = 0
        self._search_calls = 0
        self._records_scanned_total = 0
        self._results_returned_total = 0
        try:
            cap = context.get_capability("retrieval.reranker")
        except Exception:
            cap = None
        if cap is not None:
            self._rerankers = capability_providers(cap, "retrieval.reranker")

    def capabilities(self) -> dict[str, Any]:
        return {"retrieval.strategy": self}

    def trace(self) -> list[dict[str, Any]]:
        return list(self._last_trace)

    def search(self, query: str, time_window: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        started = time.perf_counter()
        store = self.context.get_capability("storage.metadata")
        if store is None:
            return []
        query_text = str(query or "").strip()
        if not query_text:
            return []
        retrieval_cfg = self._config.get("retrieval", {}) if isinstance(self._config, dict) else {}
        try:
            max_return = int(retrieval_cfg.get("result_limit", retrieval_cfg.get("limit", 25)) or 25)
        except Exception:
            max_return = 25
        max_return = max(1, max_return)
        trace: list[dict[str, Any]] = []
        scan_stats: dict[str, int] = {"records_scanned": 0}
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
            retrieval_cfg = self._config.get("retrieval", {}) if isinstance(self._config, dict) else {}
            allow_full_scan = bool(retrieval_cfg.get("allow_full_scan", False))
            latest_scan_on_miss = bool(retrieval_cfg.get("latest_scan_on_miss", True))
            try:
                latest_scan_limit = int(retrieval_cfg.get("latest_scan_limit", 2000) or 2000)
            except Exception:
                latest_scan_limit = 2000
            env_latest_on_miss = str(os.environ.get("AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_ON_MISS") or "").strip().casefold()
            if env_latest_on_miss in {"1", "true", "yes", "on"}:
                latest_scan_on_miss = True
            elif env_latest_on_miss in {"0", "false", "no", "off"}:
                latest_scan_on_miss = False
            env_latest_limit = str(os.environ.get("AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT") or "").strip()
            if env_latest_limit:
                try:
                    latest_scan_limit = int(env_latest_limit)
                except Exception:
                    pass
            latest_scan_limit = max(0, latest_scan_limit)
            latest_scan_record_types = retrieval_cfg.get("latest_scan_record_types")
            if candidate_ids is not None:
                results = _scan_metadata(store, query_text, time_window, candidate_ids, stats=scan_stats, stop_after=max_return)
                trace.append({"tier": "CANDIDATE_SCAN", "result_count": len(results)})
            elif allow_full_scan:
                results = _scan_metadata(store, query_text, time_window, candidate_ids, stats=scan_stats, stop_after=max_return)
                trace.append({"tier": "FULL_SCAN", "result_count": len(results)})
            elif latest_scan_on_miss and latest_scan_limit > 0:
                results = _scan_metadata_latest(
                    store,
                    query_text,
                    time_window,
                    limit=latest_scan_limit,
                    record_types=latest_scan_record_types,
                    stats=scan_stats,
                    stop_after=max_return,
                )
                trace.append({"tier": "LATEST_SCAN", "result_count": len(results), "limit": int(latest_scan_limit)})
            else:
                trace.append({"tier": "FULL_SCAN_SKIPPED", "reason": "disabled"})
        results.sort(
            key=lambda r: (
                -float(r.get("score", 0.0)),
                -(_ts_key(r.get("ts_utc")) or 0.0),
                str(r.get("record_type", "")),
                str(r.get("record_id", "")),
                str(r.get("derived_id", "")),
            )
        )
        if len(results) > max_return:
            trace.append({"tier": "RESULT_TRUNCATE", "from": len(results), "to": int(max_return)})
            results = results[:max_return]
        attach_timelines = bool(retrieval_cfg.get("attach_timelines", True))
        env_attach_timelines = str(os.environ.get("AUTOCAPTURE_RETRIEVAL_ATTACH_TIMELINES") or "").strip().casefold()
        if env_attach_timelines in {"1", "true", "yes", "on"}:
            attach_timelines = True
        elif env_attach_timelines in {"0", "false", "no", "off"}:
            attach_timelines = False
        elif str(os.environ.get("AUTOCAPTURE_QUERY_METADATA_ONLY") or "").strip().casefold() in {"1", "true", "yes", "on"}:
            attach_timelines = False
        if attach_timelines:
            try:
                timeline_limit = int(retrieval_cfg.get("timeline_scan_limit", 5000))
            except Exception:
                timeline_limit = 5000
            env_timeline_limit = str(os.environ.get("AUTOCAPTURE_RETRIEVAL_TIMELINE_SCAN_LIMIT") or "").strip()
            if env_timeline_limit:
                try:
                    timeline_limit = int(env_timeline_limit)
                except Exception:
                    pass
            timeline_limit = max(0, int(timeline_limit))
            window_events, input_summaries, cursor_samples = _collect_timelines(store, limit=timeline_limit)
            _attach_timelines(results, store, window_events, input_summaries, cursor_samples)
        elapsed_ms = float((time.perf_counter() - started) * 1000.0)
        self._record_perf(elapsed_ms=elapsed_ms, scanned=int(scan_stats.get("records_scanned", 0) or 0), returned=int(len(results)))
        elapsed_s = max(1e-9, elapsed_ms / 1000.0)
        trace.append(
            {
                "tier": "PERF",
                "search_ms": float(round(elapsed_ms, 3)),
                "records_scanned": int(scan_stats.get("records_scanned", 0) or 0),
                "results_returned": int(len(results)),
                "throughput_results_per_s": float(round(float(len(results)) / elapsed_s, 3)),
                "throughput_scanned_per_s": float(round(float(scan_stats.get("records_scanned", 0) or 0) / elapsed_s, 3)),
                "latency_histogram_ms": dict(self._latency_hist_counts),
                "search_calls_total": int(self._search_calls),
                "records_scanned_total": int(self._records_scanned_total),
                "results_returned_total": int(self._results_returned_total),
            }
        )
        self._last_trace = trace
        return results

    def _record_perf(self, *, elapsed_ms: float, scanned: int, returned: int) -> None:
        self._search_calls += 1
        self._records_scanned_total += max(0, int(scanned))
        self._results_returned_total += max(0, int(returned))
        value = max(0.0, float(elapsed_ms))
        bucket = "gt_5000ms"
        for edge in self._latency_hist_edges_ms:
            if value <= float(edge):
                bucket = f"le_{int(edge)}ms"
                break
        self._latency_hist_counts[bucket] = int(self._latency_hist_counts.get(bucket, 0) or 0) + 1

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._indexes_ready = True
        if not self._config:
            return
        logger = self.context.logger if callable(getattr(self.context, "logger", None)) else None
        # Retrieval runs under a read-only filesystem sandbox (see plugin manifest).
        # Index creation and writes happen in the SST pipeline; retrieval only reads.
        self._lexical, self._vector = build_indexes(self._config, logger=logger, read_only=True)
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
        def _source_id_for(doc_id: str) -> str:
            try:
                record = store.get(doc_id, {})
            except Exception:
                record = {}
            if isinstance(record, dict):
                return str(record.get("source_id") or record.get("source_record_id") or doc_id)
            return str(doc_id)

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
            # Candidate IDs are evidence/source IDs; lexical index doc_ids are often
            # derived doc IDs. Filter by the derived doc's source_id mapping.
            filtered = []
            for hit in lexical_hits:
                doc_id = hit.get("doc_id")
                if not doc_id:
                    continue
                if _source_id_for(str(doc_id)) in candidate_ids:
                    filtered.append(hit)
            lexical_hits = filtered
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
                    filtered = []
                    for hit in vector_hits:
                        doc_id = hit.get("doc_id")
                        if not doc_id:
                            continue
                        if _source_id_for(str(doc_id)) in candidate_ids:
                            filtered.append(hit)
                    vector_hits = filtered
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
            record = _store_get_safe(store, str(doc_id), {})
            if not isinstance(record, dict):
                record = {}
            docs.append({**item, "doc_id": doc_id, "text": record.get("text", "")})
        reranked = list(docs)
        # Apply any plugin-provided rerankers first (late interaction, etc.),
        # then always apply the deterministic overlap fallback to stabilize ties.
        for _pid, rr in self._rerankers:
            try:
                if hasattr(rr, "rerank"):
                    out = rr.rerank(query, reranked)
                elif callable(rr):
                    out = rr(query, reranked)
                else:
                    out = None
            except Exception:
                out = None
            if isinstance(out, list) and out:
                reranked = out
        return self._rerank_fallback.rerank(query, reranked)


def create_plugin(plugin_id: str, context: PluginContext) -> RetrievalStrategy:
    return RetrievalStrategy(plugin_id, context)


def _collect_timelines(
    store: Any,
    *,
    limit: int = 5000,
) -> tuple[list[tuple[float, str, dict[str, Any]]], list[tuple[float, float, str]], list[tuple[float, str]]]:
    window_events: list[tuple[float, str, dict[str, Any]]] = []
    input_summaries: list[tuple[float, float, str]] = []
    cursor_samples: list[tuple[float, str]] = []
    if hasattr(store, "latest"):
        try:
            for item in store.latest("evidence.window.meta", limit=limit):
                rid = str(item.get("record_id", ""))
                record = item.get("record")
                if not rid or not isinstance(record, dict):
                    continue
                ts_val = _ts_key(record.get("ts_utc"))
                if ts_val is not None:
                    window_events.append((ts_val, rid, record))
            for item in store.latest("derived.input.summary", limit=limit):
                rid = str(item.get("record_id", ""))
                record = item.get("record")
                if not rid or not isinstance(record, dict):
                    continue
                start_ts = _ts_key(record.get("start_ts_utc") or record.get("ts_start_utc"))
                end_ts = _ts_key(record.get("end_ts_utc") or record.get("ts_end_utc"))
                if start_ts is not None and end_ts is not None:
                    input_summaries.append((start_ts, end_ts, rid))
            for item in store.latest("derived.cursor.sample", limit=limit):
                rid = str(item.get("record_id", ""))
                record = item.get("record")
                if not rid or not isinstance(record, dict):
                    continue
                ts_val = _ts_key(record.get("ts_utc"))
                if ts_val is not None:
                    cursor_samples.append((ts_val, rid))
            return window_events, input_summaries, cursor_samples
        except Exception:
            pass

    max_records = max(0, int(limit))
    for idx, record_id in enumerate(_store_keys_safe(store)):
        if max_records and idx >= max_records:
            break
        record = _store_get_safe(store, record_id, {})
        if not isinstance(record, dict):
            continue
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
    query_text: str,
    time_window: dict[str, Any] | None,
    candidate_ids: set[str] | None = None,
    *,
    stats: dict[str, int] | None = None,
    stop_after: int = 0,
) -> list[dict[str, Any]]:
    query_lower = str(query_text or "").strip().lower()
    if not query_lower:
        return []
    query_tokens = _query_tokens(query_lower)
    results: list[dict[str, Any]] = []
    record_ids = _store_keys_safe(store)
    if candidate_ids is not None:
        record_ids = [rid for rid in record_ids if rid in candidate_ids]
    for record_id in record_ids:
        if isinstance(stats, dict):
            stats["records_scanned"] = int(stats.get("records_scanned", 0) or 0) + 1
        record = _store_get_safe(store, record_id, {})
        row = _scan_metadata_match_row(
            str(record_id),
            record,
            query_lower=query_lower,
            query_tokens=query_tokens,
            time_window=time_window,
        )
        if row:
            results.append(row)
            if int(stop_after) > 0 and len(results) >= int(stop_after):
                break
    return results


def _scan_metadata_latest(
    store: Any,
    query_text: str,
    time_window: dict[str, Any] | None,
    *,
    limit: int,
    record_types: Any,
    stats: dict[str, int] | None = None,
    stop_after: int = 0,
) -> list[dict[str, Any]]:
    cap = max(0, int(limit or 0))
    if cap <= 0:
        return []
    if not hasattr(store, "latest"):
        return []
    record_type_list = _resolve_latest_scan_record_types(record_types)
    if not record_type_list:
        return []
    per_type = max(1, cap // max(1, len(record_type_list)))
    query_lower = str(query_text or "").strip().lower()
    if not query_lower:
        return []
    query_tokens = _query_tokens(query_lower)
    rows_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if _latest_filtered_scan_is_expensive(store):
        allowed_types = {str(item) for item in record_type_list}
        try:
            rows = store.latest(None, limit=cap)
        except Exception:
            rows = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                record_id = str(row.get("record_id") or "").strip()
                if not record_id or record_id in seen:
                    continue
                seen.add(record_id)
                if isinstance(stats, dict):
                    stats["records_scanned"] = int(stats.get("records_scanned", 0) or 0) + 1
                record = row.get("record")
                if not isinstance(record, dict):
                    record = _store_get_safe(store, record_id, {})
                if not isinstance(record, dict):
                    continue
                record_type_val = str(record.get("record_type") or "").strip()
                if record_type_val not in allowed_types:
                    continue
                match = _scan_metadata_match_row(
                    record_id,
                    record,
                    query_lower=query_lower,
                    query_tokens=query_tokens,
                    time_window=time_window,
                )
                if match:
                    rows_out.append(match)
                    if int(stop_after) > 0 and len(rows_out) >= int(stop_after):
                        return rows_out
                if len(seen) >= cap:
                    break
        return rows_out
    for record_type in record_type_list:
        try:
            rows = store.latest(str(record_type), limit=per_type)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_id = str(row.get("record_id") or "").strip()
            if not record_id or record_id in seen:
                continue
            seen.add(record_id)
            if isinstance(stats, dict):
                stats["records_scanned"] = int(stats.get("records_scanned", 0) or 0) + 1
            record = row.get("record")
            if not isinstance(record, dict):
                record = _store_get_safe(store, record_id, {})
            match = _scan_metadata_match_row(
                record_id,
                record,
                query_lower=query_lower,
                query_tokens=query_tokens,
                time_window=time_window,
            )
            if match:
                rows_out.append(match)
                if int(stop_after) > 0 and len(rows_out) >= int(stop_after):
                    return rows_out
            if len(seen) >= cap:
                break
        if len(seen) >= cap:
            break
    return rows_out


def _latest_filtered_scan_is_expensive(store: Any) -> bool:
    target = store
    visited: set[int] = set()
    for _ in range(3):
        marker = id(target)
        if marker in visited:
            break
        visited.add(marker)
        inner = getattr(target, "_store", None)
        if inner is None or inner is target:
            break
        target = inner
    if bool(getattr(target, "_latest_filtered_expensive", False)):
        return True
    return str(target.__class__.__name__) in {"EncryptedSQLiteStore"}


def _scan_metadata_match_row(
    record_id: str,
    record: Any,
    *,
    query_lower: str,
    query_tokens: list[str],
    time_window: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    search_blob = _record_search_blob(record)
    if not search_blob:
        return None
    matched, score, snippet = _match_query_in_blob(search_blob, query_lower=query_lower, query_tokens=query_tokens)
    if not matched:
        return None
    ts = record.get("ts_utc")
    if not _within_window(ts, time_window):
        return None
    source_id = record.get("source_id") or record.get("source_record_id") or record_id
    derived_id = str(record_id) if str(source_id) != str(record_id) else None
    result: dict[str, Any] = {
        "record_id": str(source_id),
        "score": float(score),
        "ts_utc": ts,
        "record_type": str(record.get("record_type") or ""),
        "snippet": snippet,
    }
    if derived_id:
        result["derived_id"] = derived_id
    return result


def _map_candidates(
    candidates: list[dict[str, Any]],
    store: Any,
    time_window: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    # Keep multiple derived hits per evidence. Collapsing to one-per-source can
    # hide important derived docs (e.g., deterministic QA extra docs) that answer
    # different facets of the same screenshot.
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in candidates:
        doc_id = item.get("doc_id") or item.get("record_id")
        if not doc_id:
            continue
        doc_id = str(doc_id)
        record = _store_get_safe(store, doc_id, {})
        if not isinstance(record, dict):
            record = {}
        if not record:
            # In subprocess hosting, capability-to-capability calls can be
            # expensive and occasionally fragile for large derived payloads.
            # For derived.text.* doc_ids we can infer the evidence/source_id
            # deterministically from the encoded source suffix, then fetch only
            # the (small) evidence record for ts/type.
            try:
                doc_str = str(doc_id)
                parts = doc_str.split("/")
                inferred_source: str | None = None
                if len(parts) >= 3 and parts[1].startswith("derived.text."):
                    inferred_source = decode_record_id_component(parts[-1])
                if inferred_source and inferred_source != doc_str:
                    source_record = _store_get_safe(store, inferred_source, {}) or {}
                    if not isinstance(source_record, dict):
                        source_record = {}
                    if not source_record:
                        continue
                    ts = source_record.get("ts_utc")
                    if not _within_window(ts, time_window):
                        continue
                    score = float(item.get("score", 0.0))
                    record_type = str(source_record.get("record_type", ""))
                    key = (str(inferred_source), str(doc_str))
                    if key in seen:
                        continue
                    seen.add(key)
                    result = {
                        "record_id": str(inferred_source),
                        "score": score,
                        "ts_utc": ts,
                        "record_type": record_type,
                        "derived_id": doc_str,
                    }
                    snippet = item.get("snippet")
                    if snippet:
                        result["snippet"] = snippet
                    results.append(result)
                    continue
            except Exception:
                pass
        if not record:
            continue
        source_id = record.get("source_id") or record.get("source_record_id") or doc_id
        source_record = record if source_id == doc_id else _store_get_safe(store, str(source_id), {})
        if not isinstance(source_record, dict):
            source_record = {}
        if source_id != doc_id and not source_record:
            continue
        ts = record.get("ts_utc") or source_record.get("ts_utc")
        if not _within_window(ts, time_window):
            continue
        score = float(item.get("score", 0.0))
        record_type = str(source_record.get("record_type", ""))
        derived_id = str(doc_id) if source_id != doc_id else None
        key = (str(source_id), derived_id)
        if key in seen:
            continue
        seen.add(key)
        result = {"record_id": str(source_id), "score": score, "ts_utc": ts, "record_type": record_type}
        if derived_id is not None:
            result["derived_id"] = derived_id
        snippet = item.get("snippet")
        if snippet:
            result["snippet"] = snippet
        results.append(result)
    return results


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
        record = _store_get_safe(store, str(record_id), {})
        if not isinstance(record, dict):
            continue
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


def _store_keys_safe(store: Any) -> list[str]:
    try:
        keys = getattr(store, "keys", lambda: [])()
    except Exception:
        return []
    try:
        return sorted(str(k) for k in keys)
    except Exception:
        return []


def _store_get_safe(store: Any, record_id: str, default: Any) -> Any:
    try:
        return store.get(record_id, default)
    except Exception:
        return default


_DEFAULT_LATEST_SCAN_RECORD_TYPES = (
    "derived.text.ocr",
    "derived.text.vlm",
    "derived.sst.text",
    "obs.uia.focus",
    "obs.uia.context",
    "obs.uia.operable",
    "evidence.window.meta",
    "evidence.uia.snapshot",
    "evidence.capture.frame",
    "derived.input.summary",
)


def _resolve_latest_scan_record_types(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            item_str = str(item or "").strip()
            if not item_str:
                continue
            out.append(item_str)
        if out:
            return out
    return list(_DEFAULT_LATEST_SCAN_RECORD_TYPES)


def _query_tokens(query_lower: str) -> list[str]:
    tokens = [tok for tok in re.findall(r"[a-z0-9]{2,}", str(query_lower or "").lower()) if tok]
    # Preserve stable order while removing duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _clip_text(text: Any, limit: int = 400) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    cap = max(16, int(limit))
    if len(s) <= cap:
        return s
    return s[: cap - 3] + "..."


def _append_node_text(parts: list[str], node: Any, *, max_name_chars: int = 180) -> None:
    if not isinstance(node, dict):
        return
    for key in ("name", "role", "class", "aid", "eid", "hot"):
        if key not in node:
            continue
        limit = max_name_chars if key == "name" else 96
        value = _clip_text(node.get(key), limit=limit)
        if value:
            parts.append(value)


def _record_search_blob(record: dict[str, Any]) -> str:
    parts: list[str] = []

    def _add(value: Any, *, limit: int = 320) -> None:
        text = _clip_text(value, limit=limit)
        if text:
            parts.append(text)

    record_type = str(record.get("record_type") or "")
    _add(record_type, limit=128)
    _add(record.get("text"), limit=4000)

    window = record.get("window")
    if isinstance(window, dict):
        _add(window.get("title"), limit=400)
        _add(window.get("process_path"), limit=260)
        _add(window.get("pid"), limit=32)

    window_ref = record.get("window_ref")
    if isinstance(window_ref, dict):
        _add(window_ref.get("record_id"), limit=200)
        nested_window = window_ref.get("window")
        if isinstance(nested_window, dict):
            _add(nested_window.get("title"), limit=400)
            _add(nested_window.get("process_path"), limit=260)
            _add(nested_window.get("pid"), limit=32)

    input_ref = record.get("input_ref")
    if isinstance(input_ref, dict):
        _add(input_ref.get("record_id"), limit=200)

    meta = record.get("meta")
    if isinstance(meta, dict):
        _add(meta.get("window_title"), limit=420)
        _add(meta.get("window_pid"), limit=32)
        _add(meta.get("hwnd"), limit=64)
        nodes = meta.get("uia_nodes")
        if isinstance(nodes, list):
            for node in nodes[:24]:
                _append_node_text(parts, node)

    if record_type == "evidence.uia.snapshot":
        for section in ("focus_path", "context_peers", "operables"):
            rows = record.get(section)
            if not isinstance(rows, list):
                continue
            for node in rows[:24]:
                _append_node_text(parts, node)

    if record_type.startswith("obs.uia."):
        nodes = record.get("nodes")
        if isinstance(nodes, list):
            for node in nodes[:24]:
                _append_node_text(parts, node)

    if record_type == "evidence.capture.frame":
        uia_ref = record.get("uia_ref")
        if isinstance(uia_ref, dict):
            _add(uia_ref.get("record_id"), limit=220)
            _add(uia_ref.get("content_hash"), limit=96)

    if not parts:
        try:
            raw = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        except Exception:
            raw = ""
        _add(raw, limit=4000)

    return "\n".join(part for part in parts if part).strip()


def _match_query_in_blob(search_blob: str, *, query_lower: str, query_tokens: list[str]) -> tuple[bool, float, str]:
    blob = str(search_blob or "").strip()
    if not blob:
        return False, 0.0, ""
    blob_lower = blob.lower()
    direct = bool(query_lower and query_lower in blob_lower)
    token_hits: list[str] = [tok for tok in query_tokens if tok and tok in blob_lower]
    if not direct and not token_hits:
        return False, 0.0, ""
    token_ratio = float(len(token_hits)) / float(len(query_tokens)) if query_tokens else 0.0
    score = 1.0 + (0.5 * token_ratio) + (0.5 if direct else 0.0)
    snippet = _build_match_snippet(blob, blob_lower=blob_lower, query_lower=query_lower, token_hits=token_hits)
    return True, float(round(score, 6)), snippet


def _build_match_snippet(blob: str, *, blob_lower: str, query_lower: str, token_hits: list[str]) -> str:
    pivot = -1
    needle = ""
    if query_lower:
        pivot = blob_lower.find(query_lower)
        needle = query_lower
    if pivot < 0:
        for token in token_hits:
            idx = blob_lower.find(token)
            if idx >= 0:
                pivot = idx
                needle = token
                break
    if pivot < 0:
        return _clip_text(blob, limit=260)
    width = max(80, min(260, 80 + len(needle) * 2))
    start = max(0, pivot - (width // 2))
    end = min(len(blob), start + width)
    snippet = blob[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(blob):
        snippet = snippet + "..."
    return snippet


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
