"""Diffusion harness devtools plugin."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from tools.hypervisor.hypervisor import run_diffusion


class DiffusionHarness(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"devtools.diffusion": self}

    def run(self, axis: str, k_variants: int | None = None, dry_run: bool | None = None) -> dict[str, Any]:
        cfg = self.context.config.get("devtools", {}).get("diffusion", {})
        k = k_variants if k_variants is not None else cfg.get("k_variants", 1)
        dry = dry_run if dry_run is not None else cfg.get("dry_run", True)
        return run_diffusion(axis=axis, k_variants=k, dry_run=dry)


def create_plugin(plugin_id: str, context: PluginContext) -> DiffusionHarness:
    return DiffusionHarness(plugin_id, context)
