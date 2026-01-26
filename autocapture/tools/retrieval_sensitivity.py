"""Retrieval sensitivity gate validates deterministic ranking."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy


class _Store:
    def __init__(self, records: dict[str, dict[str, Any]]) -> None:
        self._records = records

    def keys(self):
        return list(self._records.keys())

    def get(self, key: str, default=None):
        return self._records.get(key, default)


def run() -> dict:
    issues: list[str] = []
    records = {
        "b": {"text": "alpha", "ts_utc": "2026-01-01T00:00:00+00:00"},
        "a": {"text": "alpha", "ts_utc": "2026-01-01T00:00:00+00:00"},
        "c": {"text": "alpha", "ts_utc": "2026-01-02T00:00:00+00:00"},
    }
    store = _Store(records)
    ctx = PluginContext(config={}, get_capability=lambda name: store if name == "storage.metadata" else None, logger=lambda _m: None)
    strategy = RetrievalStrategy("gate.retrieval", ctx)
    first = strategy.search("alpha")
    second = strategy.search("alpha")
    if first != second:
        issues.append("non_deterministic_results")
    if first and first[0]["record_id"] != "c":
        issues.append("ordering_not_timestamp_then_id")
    return {"ok": len(issues) == 0, "issues": issues}
