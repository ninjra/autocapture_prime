"""Runtime governor enforcing heavy-work gating and idle budgets."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Mapping

from autocapture.runtime.budgets import resolve_idle_budgets


MODES = {
    "ACTIVE_CAPTURE_ONLY",
    "IDLE_DRAIN",
    "USER_QUERY",
}


@dataclass(frozen=True)
class BudgetSnapshot:
    window_started_at: float | None
    window_ends_at: float | None
    spent_ms: int
    remaining_ms: int
    jobs_run: int
    jobs_remaining: int
    inflight_heavy: int
    budget_ms: int


@dataclass(frozen=True)
class GovernorDecision:
    mode: str
    heavy_allowed: bool
    reason: str
    idle_seconds: float
    activity_score: float
    mode_changed: bool
    budget: BudgetSnapshot


class BudgetLease:
    """Lease representing an admitted heavy job against the idle budget."""

    def __init__(
        self,
        governor: RuntimeGovernor,
        job_name: str,
        *,
        allowed: bool,
        granted_ms: int,
        heavy: bool,
    ) -> None:
        self._governor = governor
        self.job_name = job_name
        self.allowed = allowed
        self.granted_ms = int(max(0, granted_ms))
        self.heavy = bool(heavy)
        self._start = time.monotonic()
        self._closed = False

    def record(self, consumed_ms: int | None = None) -> int:
        if self._closed:
            return 0
        if consumed_ms is None:
            consumed_ms = int(max(0.0, (time.monotonic() - self._start) * 1000.0))
        consumed_ms = int(max(0, consumed_ms))
        self._governor._record_consumed(self, consumed_ms)
        self._closed = True
        return consumed_ms

    def close(self) -> None:
        self.record(0)

    def __enter__(self) -> BudgetLease:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.record(None)


class RuntimeGovernor:
    def __init__(self, idle_window_s: int = 45, suspend_workers: bool = True) -> None:
        self.idle_window_s = int(idle_window_s)
        self.suspend_workers = bool(suspend_workers)
        self._budgets = resolve_idle_budgets({"runtime": {"idle_window_s": self.idle_window_s}})
        self._lock = threading.Lock()
        self._last_mode = "ACTIVE_CAPTURE_ONLY"
        self._mode_changed_at = time.monotonic()
        self._last_signals: dict[str, Any] = {}
        self._window_started_at: float | None = None
        self._window_spent_ms = 0
        self._window_jobs_run = 0
        self._inflight_heavy = 0
        self._suspend_deadline_ms = 0

    def update_config(self, config: Mapping[str, Any]) -> None:
        budgets = resolve_idle_budgets(config)
        runtime_cfg = config.get("runtime", {}) if isinstance(config, Mapping) else {}
        idle_window_s = int(runtime_cfg.get("idle_window_s", budgets.min_idle_seconds))
        suspend_workers = bool(runtime_cfg.get("mode_enforcement", {}).get("suspend_workers", self.suspend_workers))
        suspend_deadline_ms = int(runtime_cfg.get("mode_enforcement", {}).get("suspend_deadline_ms", 500) or 500)
        with self._lock:
            self.idle_window_s = idle_window_s
            self.suspend_workers = suspend_workers
            self._budgets = budgets
            self._suspend_deadline_ms = max(0, suspend_deadline_ms)
            self._reset_window_locked()

    def _reset_window_locked(self) -> None:
        self._window_started_at = None
        self._window_spent_ms = 0
        self._window_jobs_run = 0
        self._inflight_heavy = 0

    def _ensure_window_locked(self, now: float) -> None:
        window_s = max(1, int(self._budgets.window_s))
        if self._window_started_at is None:
            self._window_started_at = now
            self._window_spent_ms = 0
            self._window_jobs_run = 0
            return
        if now - self._window_started_at >= window_s:
            self._window_started_at = now
            self._window_spent_ms = 0
            self._window_jobs_run = 0

    def _budget_snapshot_locked(self, now: float) -> BudgetSnapshot:
        window_s = max(1, int(self._budgets.window_s))
        window_started_at = self._window_started_at
        window_ends_at = (window_started_at + window_s) if window_started_at is not None else None
        budget_ms = max(0, int(self._budgets.window_budget_ms))
        spent_ms = max(0, int(self._window_spent_ms))
        remaining_ms = max(0, budget_ms - spent_ms)
        jobs_limit = int(self._budgets.max_jobs_per_window)
        jobs_run = max(0, int(self._window_jobs_run))
        jobs_remaining = (jobs_limit - jobs_run) if jobs_limit > 0 else -1
        return BudgetSnapshot(
            window_started_at=window_started_at,
            window_ends_at=window_ends_at,
            spent_ms=spent_ms,
            remaining_ms=remaining_ms,
            jobs_run=jobs_run,
            jobs_remaining=jobs_remaining,
            inflight_heavy=max(0, int(self._inflight_heavy)),
            budget_ms=budget_ms,
        )

    def _compute_mode_locked(self, signals: Mapping[str, Any]) -> tuple[str, str, float, float]:
        idle_seconds = float(signals.get("idle_seconds", 0.0))
        activity_score = float(signals.get("activity_score", 0.0) or 0.0)
        activity_recent = bool(signals.get("activity_recent", False))
        user_active = bool(signals.get("user_active", False)) or activity_score >= 0.5 or activity_recent
        fullscreen_active = bool(signals.get("fullscreen_active", False))
        query_intent = bool(signals.get("query_intent", False))
        suspend_workers = bool(signals.get("suspend_workers", self.suspend_workers))
        allow_active = bool(self._budgets.allow_heavy_during_active)
        min_idle = max(0, int(self._budgets.min_idle_seconds))
        cpu_util = signals.get("cpu_utilization")
        ram_util = signals.get("ram_utilization")
        cpu_limit = float(self._budgets.cpu_max_utilization)
        ram_limit = float(self._budgets.ram_max_utilization)

        if fullscreen_active:
            return "ACTIVE_CAPTURE_ONLY", "fullscreen", idle_seconds, activity_score
        if cpu_util is not None:
            try:
                if float(cpu_util) >= cpu_limit > 0:
                    return "ACTIVE_CAPTURE_ONLY", "resource_budget", idle_seconds, activity_score
            except Exception:
                pass
        if ram_util is not None:
            try:
                if float(ram_util) >= ram_limit > 0:
                    return "ACTIVE_CAPTURE_ONLY", "resource_budget", idle_seconds, activity_score
            except Exception:
                pass

        if query_intent:
            return "USER_QUERY", "query_intent", idle_seconds, activity_score
        if user_active and suspend_workers and not allow_active:
            return "ACTIVE_CAPTURE_ONLY", "active_user", idle_seconds, activity_score
        if idle_seconds >= min_idle:
            return "IDLE_DRAIN", "idle_window", idle_seconds, activity_score
        if user_active and not suspend_workers and allow_active:
            return "IDLE_DRAIN", "active_allowed", idle_seconds, activity_score
        return "ACTIVE_CAPTURE_ONLY", "idle_threshold", idle_seconds, activity_score

    def _decide_locked(self, signals: Mapping[str, Any]) -> GovernorDecision:
        now = time.monotonic()
        mode, base_reason, idle_seconds, activity_score = self._compute_mode_locked(signals)
        mode_changed = mode != self._last_mode
        if mode_changed or now < self._mode_changed_at:
            self._last_mode = mode
            self._mode_changed_at = now
        self._last_signals = dict(signals)

        if mode != "IDLE_DRAIN":
            self._reset_window_locked()
            budget = self._budget_snapshot_locked(now)
            heavy_allowed = mode == "USER_QUERY"
            return GovernorDecision(
                mode=mode,
                heavy_allowed=heavy_allowed,
                reason=base_reason,
                idle_seconds=idle_seconds,
                activity_score=activity_score,
                mode_changed=mode_changed,
                budget=budget,
            )

        self._ensure_window_locked(now)
        budget = self._budget_snapshot_locked(now)
        concurrency_limit = max(1, int(self._budgets.max_heavy_concurrency))
        remaining_ms = budget.remaining_ms
        if remaining_ms <= 0:
            heavy_allowed = False
            reason = "budget_exhausted"
        elif budget.jobs_remaining == 0:
            heavy_allowed = False
            reason = "jobs_exhausted"
        elif budget.inflight_heavy >= concurrency_limit:
            heavy_allowed = False
            reason = "concurrency_limit"
        else:
            heavy_allowed = True
            reason = base_reason
        return GovernorDecision(
            mode=mode,
            heavy_allowed=heavy_allowed,
            reason=reason,
            idle_seconds=idle_seconds,
            activity_score=activity_score,
            mode_changed=mode_changed,
            budget=budget,
        )

    def decide(self, signals: Mapping[str, Any]) -> GovernorDecision:
        with self._lock:
            return self._decide_locked(signals)

    def should_preempt(self, signals: Mapping[str, Any] | None = None) -> bool:
        with self._lock:
            active_signals = signals or self._last_signals
            decision = self._decide_locked(active_signals)
            if bool(active_signals.get("fullscreen_active", False)):
                return True
            grace_ms = max(0, int(self._budgets.preempt_grace_ms))
            suspend_deadline = max(0, int(self._suspend_deadline_ms))
            if decision.mode != "IDLE_DRAIN" and suspend_deadline:
                grace_ms = suspend_deadline if grace_ms <= 0 else min(grace_ms, suspend_deadline)
            elapsed_ms = int(max(0.0, (time.monotonic() - self._mode_changed_at) * 1000.0))
            if decision.mode != "IDLE_DRAIN" and elapsed_ms >= grace_ms:
                return True
            if (
                decision.mode == "IDLE_DRAIN"
                and not decision.heavy_allowed
                and decision.reason in {"budget_exhausted", "jobs_exhausted"}
                and elapsed_ms >= grace_ms
            ):
                return True
            return False

    def lease(self, job_name: str, estimated_ms: int, *, heavy: bool = True) -> BudgetLease:
        estimated_ms = int(max(0, estimated_ms))
        if not heavy:
            return BudgetLease(self, job_name, allowed=True, granted_ms=0, heavy=False)
        with self._lock:
            decision = self._decide_locked(self._last_signals)
            if decision.mode != "IDLE_DRAIN" or not decision.heavy_allowed:
                return BudgetLease(self, job_name, allowed=False, granted_ms=0, heavy=True)
            per_job_max = max(0, int(self._budgets.per_job_max_ms))
            remaining = max(0, int(decision.budget.remaining_ms))
            grant = remaining
            if per_job_max:
                grant = min(grant, per_job_max)
            if estimated_ms:
                grant = min(grant, estimated_ms)
            if grant <= 0:
                return BudgetLease(self, job_name, allowed=False, granted_ms=0, heavy=True)
            self._inflight_heavy += 1
            return BudgetLease(self, job_name, allowed=True, granted_ms=grant, heavy=True)

    def _record_consumed(self, lease: BudgetLease, consumed_ms: int) -> None:
        if not lease.heavy:
            return
        with self._lock:
            if lease.allowed and self._window_started_at is not None:
                grant = lease.granted_ms or consumed_ms
                delta = min(max(0, consumed_ms), max(0, grant))
                self._window_spent_ms = int(max(0, self._window_spent_ms + delta))
                self._window_jobs_run = int(max(0, self._window_jobs_run + 1))
            if self._inflight_heavy > 0:
                self._inflight_heavy -= 1

    def budget_snapshot(self) -> BudgetSnapshot:
        with self._lock:
            now = time.monotonic()
            if self._window_started_at is not None:
                self._ensure_window_locked(now)
            return self._budget_snapshot_locked(now)


def create_governor(plugin_id: str) -> RuntimeGovernor:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    runtime_cfg = config.get("runtime", {})
    idle_window_s = int(runtime_cfg.get("idle_window_s", 45))
    suspend_workers = bool(runtime_cfg.get("mode_enforcement", {}).get("suspend_workers", True))
    governor = RuntimeGovernor(idle_window_s=idle_window_s, suspend_workers=suspend_workers)
    governor.update_config(config)
    return governor
