"""Plugin API definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class PluginContext:
    config: dict[str, Any]
    get_capability: Callable[[str], Any]
    logger: Callable[[str], None]


class PluginBase:
    """Base class for plugins (optional)."""

    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        self.plugin_id = plugin_id
        self.context = context

    def capabilities(self) -> dict[str, Any]:
        return {}

    def activate(self, _ctx: PluginContext) -> None:
        return None

    def close(self) -> None:
        return None
