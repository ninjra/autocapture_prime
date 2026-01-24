"""In-memory storage plugin (baseline)."""

from __future__ import annotations

import json
import os
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class InMemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def all(self) -> dict[str, Any]:
        return dict(self._data)

    def keys(self) -> list[str]:
        return list(self._data.keys())


class EntityMapStore:
    def __init__(self, persist: bool, data_dir: str) -> None:
        self._data: dict[str, dict[str, str]] = {}
        self._persist = persist
        self._path = os.path.join(data_dir, "entity_map.json")
        if self._persist and os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as handle:
                self._data = json.load(handle)

    def put(self, token: str, value: str, kind: str) -> None:
        self._data[token] = {"value": value, "kind": kind}
        if self._persist:
            with open(self._path, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=2, sort_keys=True)

    def get(self, token: str) -> dict[str, str] | None:
        return self._data.get(token)

    def items(self) -> dict[str, dict[str, str]]:
        return dict(self._data)


class StorageMemoryPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        data_dir = context.config.get("storage", {}).get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        persist = context.config.get("storage", {}).get("entity_map", {}).get("persist", False)
        self._metadata = InMemoryStore()
        self._media = InMemoryStore()
        self._entity_map = EntityMapStore(persist=persist, data_dir=data_dir)

    def capabilities(self) -> dict[str, Any]:
        return {
            "storage.metadata": self._metadata,
            "storage.media": self._media,
            "storage.entity_map": self._entity_map,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> StorageMemoryPlugin:
    return StorageMemoryPlugin(plugin_id, context)
