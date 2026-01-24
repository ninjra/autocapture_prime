"""Deterministic time intent parser plugin."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class TimeIntentParser(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"time.intent_parser": self}

    def parse(self, text: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        tz = self.context.config.get("runtime", {}).get("timezone", "UTC")
        lowered = text.lower()
        if "today" in lowered:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return {"query": text, "time_window": {"start": start.isoformat(), "end": end.isoformat()}, "tz": tz}
        if "yesterday" in lowered:
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end - timedelta(days=1)
            return {"query": text, "time_window": {"start": start.isoformat(), "end": end.isoformat()}, "tz": tz}
        if "tomorrow" in lowered:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end = start + timedelta(days=1)
            return {"query": text, "time_window": {"start": start.isoformat(), "end": end.isoformat()}, "tz": tz}
        return {"query": text, "time_window": None, "tz": tz}


def create_plugin(plugin_id: str, context: PluginContext) -> TimeIntentParser:
    return TimeIntentParser(plugin_id, context)
