"""Runtime conductor for idle processing and research."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from autocapture.research.runner import ResearchRunner
from autocapture.storage.pressure import StoragePressureMonitor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Job, Scheduler


@dataclass
class ConductorStats:
    last_idle_run: float | None = None
    last_research_run: float | None = None
    last_storage_sample: float | None = None


class RuntimeConductor:
    def __init__(self, system: Any) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._governor = self._resolve_governor(system)
        self._scheduler = Scheduler(self._governor)
        self._input_tracker = self._resolve_input_tracker(system)
        self._idle_processor = None
        self._storage_monitor = StoragePressureMonitor(system)
        self._research_runner = ResearchRunner(self._config)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queued: set[str] = set()
        self._stats = ConductorStats()

    def _resolve_governor(self, system: Any) -> RuntimeGovernor:
        if hasattr(system, "has") and system.has("runtime.governor"):
            return system.get("runtime.governor")
        return RuntimeGovernor()

    def _resolve_input_tracker(self, system: Any):
        if hasattr(system, "has") and system.has("tracking.input"):
            return system.get("tracking.input")
        if isinstance(system, dict):
            return system.get("tracking.input")
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

    def _signals(self) -> dict[str, Any]:
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
        return {
            "idle_seconds": idle_seconds,
            "user_active": user_active,
            "query_intent": False,
            "suspend_workers": suspend_workers,
            "allow_query_heavy": False,
        }

    def _schedule_idle(self) -> None:
        idle_cfg = self._config.get("processing", {}).get("idle", {})
        if not bool(idle_cfg.get("enabled", True)):
            return
        processor = self._resolve_idle_processor()
        if processor is None:
            return
        if "idle.extract" in self._queued:
            return

        def job_fn():
            self._stats.last_idle_run = time.time()
            processor.process(should_abort=self._should_abort)

        self._scheduler.enqueue(Job(name="idle.extract", fn=job_fn, heavy=True))
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

        def job_fn():
            self._stats.last_research_run = time.time()
            self._research_runner.run_once()

        self._scheduler.enqueue(Job(name="idle.research", fn=job_fn, heavy=True))
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

        self._scheduler.enqueue(Job(name="storage.pressure", fn=job_fn, heavy=True))
        self._queued.add("storage.pressure")

    def _should_abort(self) -> bool:
        signals = self._signals()
        decision = self._governor.decide(signals)
        return decision.mode != "IDLE_DRAIN"

    def _run_once(self) -> list[str]:
        self._schedule_idle()
        self._schedule_research()
        self._schedule_storage_pressure()
        signals = self._signals()
        executed = self._scheduler.run_pending(signals)
        for name in executed:
            self._queued.discard(name)
        return executed

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
