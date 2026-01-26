"""Journal writer plugin."""

from __future__ import annotations

import os
import threading
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class JournalWriter(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        data_dir = context.config.get("storage", {}).get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "journal.ndjson")
        self._lock = threading.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {"journal.writer": self}

    def append(self, entry: dict[str, Any]) -> None:
        required = {
            "schema_version",
            "event_id",
            "sequence",
            "ts_utc",
            "tzid",
            "offset_minutes",
            "event_type",
            "payload",
        }
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"Journal entry missing fields: {sorted(missing)}")
        canonical = dumps(entry)
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(f"{canonical}\n")


def create_plugin(plugin_id: str, context: PluginContext) -> JournalWriter:
    return JournalWriter(plugin_id, context)
