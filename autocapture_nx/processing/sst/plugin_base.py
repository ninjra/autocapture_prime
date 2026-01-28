"""Minimal deterministic plugin framework for SST stage plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PluginMeta:
    id: str
    version: str


@dataclass(frozen=True)
class RunContext:
    run_id: str
    ts_ms: int
    config: dict[str, Any]
    stores: Any
    logger: Any


@dataclass(frozen=True)
class PluginInput:
    items: dict[str, Any]


@dataclass(frozen=True)
class PluginOutput:
    items: dict[str, Any]
    metrics: dict[str, float]
    diagnostics: list[dict[str, Any]]


class Plugin(Protocol):
    meta: PluginMeta
    requires: tuple[str, ...]
    provides: tuple[str, ...]

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput: ...
