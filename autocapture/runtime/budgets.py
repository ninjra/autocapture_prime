"""Runtime budget definitions and resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class IdleBudgetConfig:
    """Idle-window budgets tuned for "ultralight active, heavy idle" behavior."""

    window_s: int
    window_budget_ms: int
    per_job_max_ms: int
    max_jobs_per_window: int
    max_heavy_concurrency: int
    preempt_grace_ms: int
    min_idle_seconds: int
    allow_heavy_during_active: bool
    cpu_max_utilization: float
    ram_max_utilization: float


DEFAULT_IDLE_BUDGETS = IdleBudgetConfig(
    window_s=120,
    window_budget_ms=8000,
    per_job_max_ms=2500,
    max_jobs_per_window=4,
    max_heavy_concurrency=1,
    preempt_grace_ms=150,
    min_idle_seconds=45,
    allow_heavy_during_active=False,
    cpu_max_utilization=0.5,
    ram_max_utilization=0.5,
)

# Backwards-compatible names used by existing imports/tests.
RuntimeBudgets = IdleBudgetConfig
DEFAULT_BUDGETS = DEFAULT_IDLE_BUDGETS


def resolve_idle_budgets(config: Mapping[str, Any]) -> IdleBudgetConfig:
    """Resolve idle budgets from config with deterministic defaults."""

    runtime_cfg = config.get("runtime", {}) if isinstance(config, Mapping) else {}
    idle_window_s = int(runtime_cfg.get("idle_window_s", DEFAULT_IDLE_BUDGETS.min_idle_seconds))
    budgets_cfg = runtime_cfg.get("budgets", {})
    if not isinstance(budgets_cfg, Mapping):
        budgets_cfg = {}

    window_s = int(budgets_cfg.get("window_s", idle_window_s))
    min_idle_raw = int(budgets_cfg.get("min_idle_seconds", DEFAULT_IDLE_BUDGETS.min_idle_seconds))
    min_idle_seconds = min_idle_raw
    if (
        min_idle_raw == DEFAULT_IDLE_BUDGETS.min_idle_seconds
        and idle_window_s != DEFAULT_IDLE_BUDGETS.min_idle_seconds
    ):
        min_idle_seconds = idle_window_s
    def _clamp_fraction(value: Any, default: float) -> float:
        try:
            num = float(value)
        except Exception:
            num = float(default)
        if num < 0:
            return 0.0
        if num > 0.5:
            return 0.5
        return num

    return IdleBudgetConfig(
        window_s=max(1, window_s),
        window_budget_ms=max(0, int(budgets_cfg.get("window_budget_ms", DEFAULT_IDLE_BUDGETS.window_budget_ms))),
        per_job_max_ms=max(0, int(budgets_cfg.get("per_job_max_ms", DEFAULT_IDLE_BUDGETS.per_job_max_ms))),
        max_jobs_per_window=max(0, int(budgets_cfg.get("max_jobs_per_window", DEFAULT_IDLE_BUDGETS.max_jobs_per_window))),
        max_heavy_concurrency=max(1, int(budgets_cfg.get("max_heavy_concurrency", DEFAULT_IDLE_BUDGETS.max_heavy_concurrency))),
        preempt_grace_ms=max(0, int(budgets_cfg.get("preempt_grace_ms", DEFAULT_IDLE_BUDGETS.preempt_grace_ms))),
        min_idle_seconds=max(0, int(min_idle_seconds)),
        allow_heavy_during_active=bool(budgets_cfg.get("allow_heavy_during_active", DEFAULT_IDLE_BUDGETS.allow_heavy_during_active)),
        cpu_max_utilization=_clamp_fraction(budgets_cfg.get("cpu_max_utilization", DEFAULT_IDLE_BUDGETS.cpu_max_utilization), DEFAULT_IDLE_BUDGETS.cpu_max_utilization),
        ram_max_utilization=_clamp_fraction(budgets_cfg.get("ram_max_utilization", DEFAULT_IDLE_BUDGETS.ram_max_utilization), DEFAULT_IDLE_BUDGETS.ram_max_utilization),
    )
