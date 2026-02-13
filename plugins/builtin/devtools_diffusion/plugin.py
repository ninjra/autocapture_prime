"""Diffusion harness devtools plugin."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.kernel.paths import resolve_repo_path


def _load_run_diffusion():
    # `tools/` is not importable inside plugin sandboxes by default. Load the
    # hypervisor helper by path so this plugin remains self-contained.
    path = resolve_repo_path("tools/hypervisor/hypervisor.py")
    spec = importlib.util.spec_from_file_location("autocapture_devtools_hypervisor", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("hypervisor_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    # dataclass/type resolution expects the module to be registered.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, "run_diffusion", None)
    if not callable(fn):
        raise RuntimeError("hypervisor_missing_run_diffusion")
    return fn


class DiffusionHarness(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"devtools.diffusion": self}

    def run(self, axis: str, k_variants: int | None = None, dry_run: bool | None = None) -> dict[str, Any]:
        cfg = self.context.config.get("devtools", {}).get("diffusion", {})
        k = k_variants if k_variants is not None else cfg.get("k_variants", 1)
        dry = dry_run if dry_run is not None else cfg.get("dry_run", True)
        run_diffusion = _load_run_diffusion()
        return run_diffusion(axis=axis, k_variants=k, dry_run=dry)


def create_plugin(plugin_id: str, context: PluginContext) -> DiffusionHarness:
    return DiffusionHarness(plugin_id, context)
