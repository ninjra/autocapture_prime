"""Basic retrieval strategy plugin with deterministic tie-breaks."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class RetrievalStrategy(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"retrieval.strategy": self}

    def search(self, query: str, time_window: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        store = self.context.get_capability("storage.metadata")
        results: list[dict[str, Any]] = []
        window_events: list[tuple[float, str, dict[str, Any]]] = []
        input_summaries: list[tuple[float, float, str]] = []
        query_lower = query.lower()
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
            text = str(record.get("text", "")).lower()
            if query_lower and query_lower not in text:
                continue
            ts = record.get("ts_utc")
            if time_window and ts:
                start = time_window.get("start")
                end = time_window.get("end")
                if start and ts < start:
                    continue
                if end and ts > end:
                    continue
            score = 1 if query_lower in text else 0
            source_id = record.get("source_id") or record_id
            derived_id = record_id if source_id != record_id else None
            result = {"record_id": source_id, "score": score, "ts_utc": ts}
            if derived_id:
                result["derived_id"] = derived_id
            results.append(result)

        # Stable ordering: score desc, timestamp desc, record_id asc
        results.sort(key=lambda r: (-r["score"], -(_ts_key(r.get("ts_utc")) or 0.0), r["record_id"]))
        _attach_timelines(results, store, window_events, input_summaries)
        return results


def create_plugin(plugin_id: str, context: PluginContext) -> RetrievalStrategy:
    return RetrievalStrategy(plugin_id, context)


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
) -> None:
    if not results:
        return
    if window_events:
        window_events.sort(key=lambda item: item[0])
    if input_summaries:
        input_summaries.sort(key=lambda item: item[0])
    window_times = [ts for ts, _rid, _record in window_events]
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
