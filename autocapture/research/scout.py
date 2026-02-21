"""Research scout implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from autocapture.core.hashing import hash_canonical
from autocapture.research.cache import ResearchCache
from autocapture.research.diff import diff_with_threshold


@dataclass
class ResearchSource:
    source_id: str
    items: list[dict[str, Any]]

    def fetch(self) -> list[dict[str, Any]]:
        return list(self.items)


@dataclass
class Watchlist:
    tags: list[str]

    def filter_items(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.tags:
            return list(items)
        selected = []
        for item in items:
            text = " ".join(str(v).lower() for v in item.values())
            if any(tag.lower() in text for tag in self.tags):
                selected.append(item)
        return selected


class ResearchScout:
    def __init__(self, source: ResearchSource, watchlist: Watchlist, cache: ResearchCache) -> None:
        self.source = source
        self.watchlist = watchlist
        self.cache = cache

    def run(self, *, threshold: float = 0.1) -> dict[str, Any]:
        cache_key = f"{self.source.source_id}:{','.join(self.watchlist.tags)}"
        cached = self.cache.get(cache_key)
        items = self.watchlist.filter_items(self.source.fetch())
        prev_items = cached.get("items", []) if cached else []
        diff = diff_with_threshold(prev_items, items, threshold=threshold)
        report = {
            "source_id": self.source.source_id,
            "items": items,
            "diff": diff,
            "cache_hit": cached is not None,
        }
        report["report_hash"] = hash_canonical(report)
        self.cache.set(cache_key, report)
        return report


def create_research_source(plugin_id: str) -> ResearchSource:
    return ResearchSource(source_id=plugin_id, items=[])


def create_watchlist(plugin_id: str) -> Watchlist:
    return Watchlist(tags=[])
