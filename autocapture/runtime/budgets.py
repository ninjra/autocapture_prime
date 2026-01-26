"""Runtime budget definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeBudgets:
    cpu_budget_ms_p95: int
    io_budget_mb_s: int
    max_queue_depth: int


DEFAULT_BUDGETS = RuntimeBudgets(cpu_budget_ms_p95=200, io_budget_mb_s=20, max_queue_depth=5)
