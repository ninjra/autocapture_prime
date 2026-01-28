"""Runtime conductor for idle processing and research."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from autocapture.research.runner import ResearchRunner
from autocapture.storage.pressure import StoragePressureMonitor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Job, JobStepResult, Scheduler
from autocapture_nx.kernel.telemetry import record_telemetry


@dataclass
class ConductorStats:
    last_idle_run: float | None = None
    last_research_run: float | None = None
    last_storage_sample: float | None = None
    last_telemetry_emit: float | None = None
    last_mode: str | None = None
    last_reason: str | None = None


class RuntimeConductor:
    def __init__(self, system: Any) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._governor = self._resolve_governor(system)
        self._scheduler = self._resolve_scheduler(system, self._governor)
        self._input_tracker = self._resolve_input_tracker(system)
        self._idle_processor = None
        self._storage_monitor = StoragePressureMonitor(system)
        self._research_runner = ResearchRunner(self._config)
        self._events = self._resolve_event_builder(system)
        self._logger = self._resolve_logger(system)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queued: set[str] = set()
        self._stats = ConductorStats()
        telemetry_cfg = self._config.get("runtime", {}).get("telemetry", {})
        self._telemetry_enabled = bool(telemetry_cfg.get("enabled", True))
        self._telemetry_interval_s = float(telemetry_cfg.get("emit_interval_s", 5))

    def _resolve_governor(self, system: Any) -> RuntimeGovernor:
        if hasattr(system, "has") and system.has("runtime.governor"):
            governor = system.get("runtime.governor")
        else:
            governor = RuntimeGovernor()
        if hasattr(governor, "update_config"):
            try:
                governor.update_config(self._config)
            except Exception:
                pass
        return governor

    def _resolve_scheduler(self, system: Any, governor: RuntimeGovernor) -> Scheduler:
        if hasattr(system, "has") and system.has("runtime.scheduler"):
            scheduler = system.get("runtime.scheduler")
        elif isinstance(system, dict) and "runtime.scheduler" in system:
            scheduler = system.get("runtime.scheduler")
        else:
            scheduler = Scheduler(governor)
        if hasattr(scheduler, "set_governor"):
            try:
                scheduler.set_governor(governor)
            except Exception:
                pass
        return scheduler

    def _resolve_input_tracker(self, system: Any):
        if hasattr(system, "has") and system.has("tracking.input"):
            return system.get("tracking.input")
        if isinstance(system, dict):
            return system.get("tracking.input")
        return None

    def _resolve_event_builder(self, system: Any):
        if hasattr(system, "has") and system.has("event.builder"):
            return system.get("event.builder")
        if isinstance(system, dict):
            return system.get("event.builder")
        return None

    def _resolve_logger(self, system: Any):
        if hasattr(system, "has") and system.has("observability.logger"):
            return system.get("observability.logger")
        if isinstance(system, dict):
            return system.get("observability.logger")
        return None

    def _resolve_idle_processor(self):
        if self._idle_processor is not None:
            return self._idle_processor
        try:
            from autocapture_nx.processing.idle import IdleProcessor
        except Exception:
            IdleProcessor = None  # type: ignore
        if IdleProcessor is None:
            return None
        self._idle_processor = IdleProcessor(self._system)
        return self._idle_processor

    def _signals(self, *, query_intent: bool | None = None) -> dict[str, Any]:
        runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
        active_window_s = float(runtime_cfg.get("active_window_s", 3))
        assume_idle = bool(runtime_cfg.get("activity", {}).get("assume_idle_when_missing", False))
        idle_seconds = 0.0
        if self._input_tracker is not None:
            try:
                idle_seconds = float(self._input_tracker.idle_seconds())
            except Exception:
                idle_seconds = 0.0
        else:
            idle_seconds = float("inf") if assume_idle else 0.0
        user_active = idle_seconds < active_window_s
        enforce_cfg = runtime_cfg.get("mode_enforcement", {})
        suspend_workers = bool(enforce_cfg.get("suspend_workers", True))
        activity_score = 0.0
        activity_recent = False
        if self._input_tracker is not None and hasattr(self._input_tracker, "activity_signal"):
            try:
                signal = self._input_tracker.activity_signal()
            except Exception:
                signal = {}
            if isinstance(signal, dict):
                idle_seconds = float(signal.get("idle_seconds", idle_seconds))
                user_active = bool(signal.get("user_active", user_active))
                activity_score = float(signal.get("activity_score", 0.0) or 0.0)
                activity_recent = bool(signal.get("recent_activity", False))
        signals = {
            "idle_seconds": idle_seconds,
            "user_active": user_active,
            "query_intent": False,
            "suspend_workers": suspend_workers,
            "allow_query_heavy": False,
            "activity_score": activity_score,
            "activity_recent": activity_recent,
        }
        if query_intent is not None:
            signals["query_intent"] = bool(query_intent)
        return signals

    def _schedule_idle(self) -> None:
        idle_cfg = self._config.get("processing", {}).get("idle", {})
        if not bool(idle_cfg.get("enabled", True)):
            return
        processor = self._resolve_idle_processor()
        if processor is None:
            return
        if "idle.extract" in self._queued:
            return

        def step_fn(should_abort, budget_ms: int) -> JobStepResult:
            self._stats.last_idle_run = time.time()
            started = time.monotonic()
            if hasattr(processor, "process_step"):
                result = processor.process_step(
                    should_abort=should_abort,
                    budget_ms=budget_ms,
                    persist_checkpoint=True,
                )
                if isinstance(result, tuple):
                    done = bool(result[0])
                else:
                    done = bool(result)
            else:
                if hasattr(processor, "process"):
                    try:
                        processor.process(should_abort=should_abort)
                    except TypeError:
                        processor.process()
                done = True
            consumed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
            return JobStepResult(done=done, consumed_ms=consumed_ms)

        estimate_ms = int(idle_cfg.get("estimate_ms", 2000))
        self._scheduler.enqueue(Job(name="idle.extract", step_fn=step_fn, heavy=True, estimated_ms=estimate_ms))
        self._queued.add("idle.extract")

    def _schedule_research(self) -> None:
        cfg = self._config.get("research", {})
        if not bool(cfg.get("enabled", True)):
            return
        if not bool(cfg.get("run_on_idle", True)):
            return
        interval_s = float(cfg.get("interval_s", 1800))
        now = time.time()
        last = self._stats.last_research_run or 0.0
        if now - last < interval_s:
            return
        if "idle.research" in self._queued:
            return

        def step_fn(should_abort, budget_ms: int) -> JobStepResult:
            self._stats.last_research_run = time.time()
            started = time.monotonic()
            if hasattr(self._research_runner, "run_step"):
                done = bool(self._research_runner.run_step(should_abort=should_abort, budget_ms=budget_ms))
            else:
                self._research_runner.run_once()
                done = True
            consumed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
            return JobStepResult(done=done, consumed_ms=consumed_ms)

        estimate_ms = int(cfg.get("estimate_ms", 1500))
        self._scheduler.enqueue(Job(name="idle.research", step_fn=step_fn, heavy=True, estimated_ms=estimate_ms))
        self._queued.add("idle.research")

    def _schedule_storage_pressure(self) -> None:
        if self._storage_monitor is None:
            return
        if not self._storage_monitor.due():
            return
        if "storage.pressure" in self._queued:
            return

        def job_fn():
            sample = self._storage_monitor.record()
            if sample is not None:
                self._stats.last_storage_sample = time.time()

        self._scheduler.enqueue(Job(name="storage.pressure", fn=job_fn, heavy=True, estimated_ms=300))
        self._queued.add("storage.pressure")

    def _should_abort(self) -> bool:
        if self._stop.is_set():
            return True
        signals = self._signals()
        if hasattr(self._governor, "should_preempt"):
            try:
                return bool(self._governor.should_preempt(signals))
            except Exception:
                pass
        decision = self._governor.decide(signals)
        return decision.mode != "IDLE_DRAIN"

    def _emit_telemetry(self, signals: dict[str, Any], executed: list[str]) -> None:
        if not self._telemetry_enabled:
            return
        now = time.time()
        last = self._stats.last_telemetry_emit or 0.0
        interval = max(0.5, float(self._telemetry_interval_s))
        if now - last < interval:
            return
        stats = self._scheduler.last_stats()
        payload = {
            "mode": stats.mode,
            "reason": stats.reason,
            "idle_seconds": float(signals.get("idle_seconds", 0.0)),
            "user_active": bool(signals.get("user_active", False)),
            "activity_score": float(signals.get("activity_score", 0.0)),
            "budget": {
                "remaining_ms": int(stats.budget_remaining_ms),
                "spent_ms": int(stats.budget_spent_ms),
                "window_ms": int(stats.budget_window_ms),
                "inflight_heavy": int(stats.inflight_heavy),
            },
            "jobs": {
                "completed": int(stats.completed_jobs),
                "admitted_heavy": int(stats.admitted_heavy),
                "deferred": int(stats.deferred_jobs),
                "preempted": int(stats.preempted_jobs),
                "ran_light": int(stats.ran_light),
            },
            "executed": list(executed),
        }
        self._stats.last_telemetry_emit = now
        self._stats.last_mode = stats.mode
        self._stats.last_reason = stats.reason
        record_telemetry("runtime", payload)
        if self._events is not None:
            try:
                self._events.journal_event("runtime.telemetry", payload)
            except Exception:
                pass
        if self._logger is not None:
            try:
                self._logger.log("runtime.telemetry", payload)
            except Exception:
                pass

    def _run_once(self, *, force: bool = False) -> list[str]:
        self._schedule_idle()
        self._schedule_research()
        self._schedule_storage_pressure()
        signals = self._signals(query_intent=True if force else None)
        executed = self._scheduler.run_pending(signals)
        self._emit_telemetry(signals, executed)
        for name in executed:
            self._queued.discard(name)
        return executed

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        executed = self._run_once(force=force)
        stats = self._scheduler.last_stats()
        return {
            "executed": executed,
            "stats": {
                "mode": stats.mode,
                "reason": stats.reason,
                "heavy_allowed": bool(stats.heavy_allowed),
                "budget_remaining_ms": int(stats.budget_remaining_ms),
                "budget_spent_ms": int(stats.budget_spent_ms),
                "budget_window_ms": int(stats.budget_window_ms),
                "inflight_heavy": int(stats.inflight_heavy),
                "admitted_heavy": int(stats.admitted_heavy),
                "completed_jobs": int(stats.completed_jobs),
                "deferred_jobs": int(stats.deferred_jobs),
                "preempted_jobs": int(stats.preempted_jobs),
                "ran_light": int(stats.ran_light),
                "ts_monotonic": float(stats.ts_monotonic),
            },
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        idle_cfg = self._config.get("processing", {}).get("idle", {})
        sleep_ms = int(idle_cfg.get("sleep_ms", 2000))
        sleep_s = max(0.1, sleep_ms / 1000.0)
        while not self._stop.is_set():
            try:
                self._run_once()
            except Exception:
                pass
            time.sleep(sleep_s)


def create_conductor(system: Any) -> RuntimeConductor:
    return RuntimeConductor(system)
