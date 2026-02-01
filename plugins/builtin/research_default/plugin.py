"""Default research source + watchlist plugin."""

from __future__ import annotations

from typing import Any, Iterable

from autocapture.research.scout import ResearchSource, Watchlist
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class ResearchSourceCap:
    def __init__(self, source_id: str) -> None:
        self._source = ResearchSource(source_id=source_id, items=[])

    def fetch(self) -> list[dict[str, Any]]:
        return self._source.fetch()

    def source_id(self) -> str:
        return self._source.source_id


class WatchlistCap:
    def __init__(self) -> None:
        self._watchlist = Watchlist(tags=[])

    def set_tags(self, tags: Iterable[str]) -> None:
        self._watchlist.tags = [str(tag) for tag in tags if str(tag).strip()]

    def filter_items(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._watchlist.filter_items(items)

    def tags(self) -> list[str]:
        return list(self._watchlist.tags)


class ResearchPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._source = ResearchSourceCap(plugin_id)
        self._watchlist = WatchlistCap()

    def capabilities(self) -> dict[str, Any]:
        return {
            "research.source": self._source,
            "research.watchlist": self._watchlist,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> ResearchPlugin:
    return ResearchPlugin(plugin_id, context)
