"""Scheduler honoring RuntimeGovernor decisions, budgets, and preemption."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Protocol

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.wsl2_queue import Wsl2Queue, Wsl2DispatchResult
from autocapture_nx.kernel.audit import append_audit_event


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
    gpu_only: bool = False
    gpu_heavy: bool = False
    payload: dict[str, Any] | None = None

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
    ran_gpu_only: int
    routed_jobs: int
    ts_monotonic: float


class Scheduler:
    def __init__(self, governor: RuntimeGovernor, *, wsl2_queue: Wsl2Queue | None = None) -> None:
        self._governor = governor
        self._queue: list[Job] = []
        self._wsl2_queue = wsl2_queue
        self._routing: dict[str, Any] = {}
        self._routing_target = "native"
        self._routing_allow_fallback = True
        self._routing_protocol = 1
        self._routing_queue_dir = "artifacts/wsl2_queue"
        self._routing_distro = ""
        self._routing_max_pending = 256
        self._routing_max_inflight = 1
        self._routing_token_ttl_s = 300.0
        snapshot = governor.budget_snapshot()
        def _snapshot_value(name: str, default: int = 0) -> int:
            if hasattr(snapshot, name):
                return int(getattr(snapshot, name))
            if isinstance(snapshot, dict):
                return int(snapshot.get(name, default) or 0)
            return int(default)
        self._last_stats = SchedulerRunStats(
            mode="ACTIVE_CAPTURE_ONLY",
            heavy_allowed=False,
            reason="init",
            budget_remaining_ms=_snapshot_value("remaining_ms"),
            budget_spent_ms=_snapshot_value("spent_ms"),
            budget_window_ms=_snapshot_value("budget_ms"),
            inflight_heavy=_snapshot_value("inflight_heavy"),
            admitted_heavy=0,
            completed_jobs=0,
            deferred_jobs=0,
            preempted_jobs=0,
            ran_light=0,
            ran_gpu_only=0,
            routed_jobs=0,
            ts_monotonic=time.monotonic(),
        )

    def enqueue(self, job: Job) -> None:
        self._queue.append(job)

    def set_governor(self, governor: RuntimeGovernor) -> None:
        self._governor = governor

    def update_config(self, config: dict[str, Any]) -> None:
        runtime_cfg = config.get("runtime", {}) if isinstance(config, dict) else {}
        routing_cfg = runtime_cfg.get("routing", {}) if isinstance(runtime_cfg, dict) else {}
        gpu_cfg = routing_cfg.get("gpu_heavy", {}) if isinstance(routing_cfg, dict) else {}
        self._routing_target = str(gpu_cfg.get("target", "native") or "native").lower()
        if self._routing_target not in {"native", "wsl2"}:
            self._routing_target = "native"
        self._routing_allow_fallback = bool(gpu_cfg.get("allow_fallback", self._routing_target != "wsl2"))
        self._routing_protocol = int(gpu_cfg.get("protocol_version", 1) or 1)
        self._routing_queue_dir = str(gpu_cfg.get("shared_queue_dir", "artifacts/wsl2_queue"))
        self._routing_distro = str(gpu_cfg.get("distro", "") or "")
        self._routing_max_pending = int(max(1, int(gpu_cfg.get("max_pending", 256) or 256)))
        self._routing_max_inflight = int(max(1, int(gpu_cfg.get("max_inflight", 1) or 1)))
        self._routing_token_ttl_s = float(max(1.0, float(gpu_cfg.get("token_ttl_s", 300.0) or 300.0)))
        if self._wsl2_queue is None or self._wsl2_queue.queue_dir != self._routing_queue_dir:
            self._wsl2_queue = Wsl2Queue(
                self._routing_queue_dir,
                protocol_version=self._routing_protocol,
                max_pending=self._routing_max_pending,
                max_inflight=self._routing_max_inflight,
                token_ttl_s=self._routing_token_ttl_s,
            )

    def set_wsl2_queue(self, queue: Wsl2Queue | None) -> None:
        self._wsl2_queue = queue

    def force_stop(self, reason: str) -> int:
        """Drop queued heavy jobs (best-effort) to honor suspend deadlines."""
        remaining: list[Job] = []
        removed = 0
        for job in self._queue:
            if job.heavy:
                removed += 1
            else:
                remaining.append(job)
        self._queue = remaining
        return removed

    def _dispatch_wsl2(self, job: Job, signals: dict[str, Any]) -> Wsl2DispatchResult | None:
        if not job.gpu_heavy:
            return None
        if self._routing_target != "wsl2":
            return None
        if self._wsl2_queue is None:
            self._wsl2_queue = Wsl2Queue(
                self._routing_queue_dir,
                protocol_version=self._routing_protocol,
                max_pending=self._routing_max_pending,
                max_inflight=self._routing_max_inflight,
                token_ttl_s=self._routing_token_ttl_s,
            )
        run_id = str(signals.get("run_id") or "")
        payload = job.payload or {"job": job.name}
        result = self._wsl2_queue.dispatch(
            job_name=job.name,
            payload=payload,
            run_id=run_id,
            distro=self._routing_distro,
            allow_fallback=self._routing_allow_fallback,
        )
        append_audit_event(
            action="wsl2.dispatch",
            actor="runtime.scheduler",
            outcome="ok" if result.ok else "error",
            details={
                "job": job.name,
                "run_id": run_id,
                "path": result.path,
                "error": result.error,
                "reason": result.reason,
                "allow_fallback": result.allow_fallback,
            },
        )
        return result

    def run_pending(self, signals: dict) -> list[str]:
        decision = self._governor.decide(signals)
        executed: list[str] = []
        remaining: list[Job] = []
        admitted_heavy = 0
        deferred = 0
        preempted = 0
        ran_light = 0
        ran_gpu_only = 0
        routed_jobs = 0
        gpu_only_allowed = bool(signals.get("gpu_only_allowed", False))
        def preempt_check() -> bool:
            return bool(self._governor.should_preempt(signals))
        for job in self._queue:
            if decision.mode == "ACTIVE_CAPTURE_ONLY":
                if job.gpu_only and gpu_only_allowed:
                    def _gpu_preempt() -> bool:
                        return False
                else:
                    remaining.append(job)
                    deferred += 1
                    continue
            else:
                def _gpu_preempt() -> bool:
                    return preempt_check()

            dispatch = self._dispatch_wsl2(job, signals)
            if dispatch is not None:
                if dispatch.ok:
                    executed.append(job.name)
                    routed_jobs += 1
                    continue
                if not dispatch.allow_fallback:
                    remaining.append(job)
                    deferred += 1
                    continue
            if (
                job.heavy
                and decision.mode == "ACTIVE_CAPTURE_ONLY"
                and not decision.heavy_allowed
                and not (job.gpu_only and gpu_only_allowed)
            ):
                remaining.append(job)
                deferred += 1
                continue

            lease = None
            budget_ms = decision.budget.remaining_ms
            if job.heavy and not (job.gpu_only and gpu_only_allowed and decision.mode == "ACTIVE_CAPTURE_ONLY"):
                lease = self._governor.lease(job.name, job.estimated_ms or decision.budget.remaining_ms, heavy=job.heavy)
                if not lease.allowed:
                    remaining.append(job)
                    deferred += 1
                    continue
                budget_ms = lease.granted_ms if lease.granted_ms > 0 else decision.budget.remaining_ms

            if job.heavy and _gpu_preempt():
                remaining.append(job)
                preempted += 1
                if lease is not None and lease.allowed:
                    lease.close()
                continue

            result = job.run(_gpu_preempt, budget_ms)
            if lease is not None and lease.allowed:
                lease.record(result.consumed_ms)
                admitted_heavy += 1
            if job.gpu_only and gpu_only_allowed and decision.mode == "ACTIVE_CAPTURE_ONLY":
                ran_gpu_only += 1
            elif not job.heavy:
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
            ran_gpu_only=ran_gpu_only,
            routed_jobs=routed_jobs,
            ts_monotonic=time.monotonic(),
        )
        return executed

    def last_stats(self) -> SchedulerRunStats:
        return self._last_stats
