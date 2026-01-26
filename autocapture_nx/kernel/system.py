"""Runtime system composed of plugin capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture_nx.plugin_system.registry import CapabilityRegistry, LoadedPlugin


@dataclass
class System:
    config: dict[str, Any]
    plugins: list[LoadedPlugin]
    capabilities: CapabilityRegistry

    def get(self, capability: str) -> Any:
        return self.capabilities.get(capability)

    def has(self, capability: str) -> bool:
        return capability in self.capabilities.all()

    def register(self, capability: str, value: Any, *, network_allowed: bool = False) -> None:
        self.capabilities.register(capability, value, network_allowed)
