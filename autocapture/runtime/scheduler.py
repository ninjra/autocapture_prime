"""Scheduler honoring RuntimeGovernor decisions, budgets, and preemption."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from autocapture.runtime.governor import RuntimeGovernor


class StepFn(Protocol):
    def __call__(self, should_abort: Callable[[], bool], budget_ms: int) -> JobStepResult: ...


@dataclass(frozen=True)
class JobStepResult:
    done: bool
    consumed_ms: int = 0


@dataclass
class Job:
    name: str
    fn: Callable[[], None] | None = None
    step_fn: StepFn | None = None
    heavy: bool = True
    estimated_ms: int = 0

    def run(self, should_abort: Callable[[], bool], budget_ms: int) -> JobStepResult:
        if should_abort():
            return JobStepResult(done=False, consumed_ms=0)
        if self.step_fn is not None:
            return self.step_fn(should_abort, int(max(0, budget_ms)))
        if self.fn is None:
            raise RuntimeError(f"job {self.name} has no callable")
        started = time.monotonic()
        self.fn()
        consumed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
        return JobStepResult(done=True, consumed_ms=consumed_ms)


@dataclass(frozen=True)
class SchedulerRunStats:
    mode: str
    heavy_allowed: bool
    reason: str
    budget_remaining_ms: int
    budget_spent_ms: int
    budget_window_ms: int
    inflight_heavy: int
    admitted_heavy: int
    completed_jobs: int
    deferred_jobs: int
    preempted_jobs: int
    ran_light: int
    ts_monotonic: float


class Scheduler:
    def __init__(self, governor: RuntimeGovernor) -> None:
        self._governor = governor
        self._queue: list[Job] = []
        snapshot = governor.budget_snapshot()
        self._last_stats = SchedulerRunStats(
            mode="ACTIVE_CAPTURE_ONLY",
            heavy_allowed=False,
            reason="init",
            budget_remaining_ms=int(snapshot.remaining_ms),
            budget_spent_ms=int(snapshot.spent_ms),
            budget_window_ms=int(snapshot.budget_ms),
            inflight_heavy=int(snapshot.inflight_heavy),
            admitted_heavy=0,
            completed_jobs=0,
            deferred_jobs=0,
            preempted_jobs=0,
            ran_light=0,
            ts_monotonic=time.monotonic(),
        )

    def enqueue(self, job: Job) -> None:
        self._queue.append(job)

    def run_pending(self, signals: dict) -> list[str]:
        decision = self._governor.decide(signals)
        executed: list[str] = []
        remaining: list[Job] = []
        admitted_heavy = 0
        deferred = 0
        preempted = 0
        ran_light = 0
        def preempt_check() -> bool:
            return bool(self._governor.should_preempt(signals))
        for job in self._queue:
            if job.heavy and decision.mode == "ACTIVE_CAPTURE_ONLY" and not decision.heavy_allowed:
                remaining.append(job)
                deferred += 1
                continue

            lease = self._governor.lease(job.name, job.estimated_ms or decision.budget.remaining_ms, heavy=job.heavy)
            if job.heavy and not lease.allowed:
                remaining.append(job)
                deferred += 1
                continue

            if job.heavy and preempt_check():
                remaining.append(job)
                preempted += 1
                if lease.allowed:
                    lease.close()
                continue

            budget_ms = lease.granted_ms if lease.allowed and lease.granted_ms > 0 else decision.budget.remaining_ms
            result = job.run(preempt_check, budget_ms)
            if job.heavy and lease.allowed:
                lease.record(result.consumed_ms)
                admitted_heavy += 1
            if not job.heavy:
                ran_light += 1
            if result.done:
                executed.append(job.name)
            else:
                remaining.append(job)
        self._queue = remaining
        snapshot = self._governor.budget_snapshot()
        self._last_stats = SchedulerRunStats(
            mode=decision.mode,
            heavy_allowed=bool(decision.heavy_allowed),
            reason=str(decision.reason),
            budget_remaining_ms=int(snapshot.remaining_ms),
            budget_spent_ms=int(snapshot.spent_ms),
            budget_window_ms=int(snapshot.budget_ms),
            inflight_heavy=int(snapshot.inflight_heavy),
            admitted_heavy=admitted_heavy,
            completed_jobs=len(executed),
            deferred_jobs=deferred,
            preempted_jobs=preempted,
            ran_light=ran_light,
            ts_monotonic=time.monotonic(),
        )
        return executed

    def last_stats(self) -> SchedulerRunStats:
        return self._last_stats
