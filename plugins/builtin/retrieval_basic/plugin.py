"""Basic retrieval strategy plugin with deterministic tie-breaks."""

from __future__ import annotations

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
        query_lower = query.lower()
        for record_id in getattr(store, "keys", lambda: [])():
            record = store.get(record_id, {})
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

        def ts_key(ts: str | None) -> float:
            if not ts:
                return 0.0
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(ts).timestamp()
            except ValueError:
                return 0.0

        # Stable ordering: score desc, timestamp desc, record_id asc
        results.sort(key=lambda r: (-r["score"], -ts_key(r.get("ts_utc")), r["record_id"]))
        return results


def create_plugin(plugin_id: str, context: PluginContext) -> RetrievalStrategy:
    return RetrievalStrategy(plugin_id, context)
