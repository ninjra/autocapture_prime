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

    def register(
        self,
        capability: str,
        value: Any,
        *,
        network_allowed: bool = False,
        filesystem_policy=None,
    ) -> None:
        self.capabilities.register(capability, value, network_allowed, filesystem_policy=filesystem_policy)

    def close(self) -> None:
        """Best-effort cleanup of plugin resources.

        Important for long-running test processes: subprocess plugin hosts can
        otherwise accumulate and exhaust RAM on WSL.
        """

        seen: set[int] = set()

        def _close_obj(obj: Any) -> None:
            if obj is None:
                return
            obj_id = id(obj)
            if obj_id in seen:
                return
            seen.add(obj_id)
            for method in ("close", "shutdown", "stop"):
                fn = getattr(obj, method, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    return

        for plugin in list(self.plugins):
            try:
                _close_obj(getattr(plugin, "instance", None))
            except Exception:
                continue

        # Clear references to capability proxies so they can be GC'ed.
        try:
            self.capabilities.replace_all({})
        except Exception:
            pass
        try:
            self.plugins = []
        except Exception:
            pass
