"""Runtime conductor for idle processing and research."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from autocapture.research.runner import ResearchRunner
from autocapture.storage.pressure import StoragePressureMonitor
from autocapture.storage.retention import StorageRetentionMonitor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.resources import sample_resources
from autocapture.runtime.gpu import release_vram
from autocapture.runtime.gpu_guard import evaluate_gpu_lag_guard
from autocapture.runtime.gpu_monitor import sample_gpu
from autocapture.runtime.scheduler import Job, JobStepResult, Scheduler
from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.kernel.telemetry import record_telemetry
from autocapture_nx.windows.fullscreen import fullscreen_snapshot


@dataclass
class ConductorStats:
    last_idle_run: float | None = None
    last_idle_ok: float | None = None
    last_idle_error: str | None = None
    last_idle_error_ts: float | None = None
    last_idle_stats: dict[str, Any] | None = None
    last_watchdog: dict[str, Any] | None = None
    last_research_run: float | None = None
    last_storage_sample: float | None = None
    last_retention_run: float | None = None
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
        self._window_tracker = self._resolve_window_tracker(system)
        self._idle_processor = None
        self._storage_monitor = StoragePressureMonitor(system)
        self._retention_monitor = StorageRetentionMonitor(system)
        self._research_runner = ResearchRunner(self._config)
        self._events = self._resolve_event_builder(system)
        self._logger = self._resolve_logger(system)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queued: set[str] = set()
        self._stats = ConductorStats()
        self._last_watchdog_state: str | None = None
        self._last_watchdog_event_ts: float | None = None
        self._last_gpu_release_ts: float | None = None
        self._last_fullscreen_state: bool | None = None
        self._last_fullscreen_ts: float | None = None
        self._last_gpu_guard_ok: bool | None = None
        self._last_gpu_guard_ts: float | None = None
        self._fullscreen_snapshot = None
        self._gpu_guard_snapshot = None
        self._suspend_requested_at: float | None = None
        self._resume_requested_at: float | None = None
        self._suspend_acked = False
        self._resume_acked = False
        self._fixture_override_audited = False
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
        if hasattr(scheduler, "update_config"):
            try:
                scheduler.update_config(self._config)
            except Exception:
                pass
        return scheduler

    def _resolve_input_tracker(self, system: Any):
        if hasattr(system, "has") and system.has("tracking.input"):
            return system.get("tracking.input")
        if isinstance(system, dict):
            return system.get("tracking.input")
        return None

    def _resolve_window_tracker(self, system: Any):
        if hasattr(system, "has") and system.has("window.metadata"):
            return system.get("window.metadata")
        if isinstance(system, dict):
            return system.get("window.metadata")
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
        fixture_override = bool(enforce_cfg.get("fixture_override", False))
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
        if fixture_override:
            idle_seconds = float("inf")
            user_active = False
            activity_score = 0.0
            activity_recent = False
            if not self._fixture_override_audited:
                self._fixture_override_audited = True
                append_audit_event(
                    action="runtime.fixture_override",
                    actor="runtime.conductor",
                    outcome="ok",
                    details={
                        "run_id": str(self._config.get("runtime", {}).get("run_id") or ""),
                        "reason": str(enforce_cfg.get("fixture_override_reason") or ""),
                    },
                )
        signals = {
            "idle_seconds": idle_seconds,
            "user_active": user_active,
            "query_intent": False,
            "suspend_workers": suspend_workers,
            "allow_query_heavy": False,
            "activity_score": activity_score,
            "activity_recent": activity_recent,
        }
        if fixture_override:
            signals["fixture_override"] = True
        resources = sample_resources()
        if resources.cpu_utilization is not None:
            signals["cpu_utilization"] = resources.cpu_utilization
        if resources.ram_utilization is not None:
            signals["ram_utilization"] = resources.ram_utilization
        if query_intent is not None:
            signals["query_intent"] = bool(query_intent)
        run_id = ""
        if isinstance(self._config, dict):
            run_id = str(self._config.get("runtime", {}).get("run_id") or "")
        if run_id:
            signals["run_id"] = run_id
        fullscreen = self._fullscreen_signal()
        if fullscreen is not None:
            signals["fullscreen_active"] = bool(fullscreen.get("fullscreen"))
            signals["fullscreen_reason"] = str(fullscreen.get("reason") or "")
        gpu_guard = self._gpu_guard_signal(user_active=bool(signals.get("user_active", False)))
        if gpu_guard is not None:
            signals["gpu_only_allowed"] = bool(gpu_guard.get("gpu_only_allowed", False))
        if bool(signals.get("fullscreen_active", False)):
            signals["gpu_only_allowed"] = False
        return signals

    def _fullscreen_signal(self) -> dict[str, Any] | None:
        runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
        fullscreen_cfg = runtime_cfg.get("fullscreen_halt", {}) if isinstance(runtime_cfg, dict) else {}
        if not bool(fullscreen_cfg.get("enabled", True)):
            self._fullscreen_snapshot = None
            return {"enabled": False, "fullscreen": False, "reason": "disabled"}
        poll_ms = float(fullscreen_cfg.get("poll_ms", 250) or 250)
        poll_s = max(0.05, min(poll_ms / 1000.0, 5.0))
        now = time.monotonic()
        if (
            self._fullscreen_snapshot is not None
            and self._last_fullscreen_ts is not None
            and (now - self._last_fullscreen_ts) < poll_s
        ):
            return self._fullscreen_snapshot
        window_ref = None
        if self._window_tracker is not None:
            try:
                if hasattr(self._window_tracker, "last_record"):
                    window_ref = self._window_tracker.last_record()
                elif hasattr(self._window_tracker, "current"):
                    window_ref = self._window_tracker.current()
            except Exception:
                window_ref = None
        snapshot = fullscreen_snapshot(window_ref)
        payload = {
            "enabled": True,
            "fullscreen": bool(snapshot.fullscreen),
            "reason": snapshot.reason,
            "ok": snapshot.ok,
            "ts_utc": snapshot.ts_utc,
            "window": snapshot.window,
        }
        self._fullscreen_snapshot = payload
        self._last_fullscreen_ts = now
        return payload

    def _gpu_guard_signal(self, *, user_active: bool) -> dict[str, Any] | None:
        runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
        gpu_cfg = runtime_cfg.get("gpu", {}) if isinstance(runtime_cfg, dict) else {}
        allow_active = bool(gpu_cfg.get("allow_during_active", False))
        device_index = int(gpu_cfg.get("device_index", 0) or 0)
        gpu_snapshot = sample_gpu(device_index)
        decision = evaluate_gpu_lag_guard(self._config, gpu=gpu_snapshot)
        self._gpu_guard_snapshot = {
            "ok": bool(decision.ok),
            "reason": decision.reason,
            "lag_p95_ms": decision.lag_p95_ms,
            "queue_p95": decision.queue_p95,
            "capture_age_s": decision.capture_age_s,
            "gpu_utilization": decision.gpu_utilization,
            "gpu_mem_utilization": decision.gpu_mem_utilization,
            "ts_monotonic": gpu_snapshot.ts_monotonic,
        }
        return {
            "gpu_only_allowed": bool(user_active and allow_active and decision.ok),
            "decision": self._gpu_guard_snapshot,
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

        def step_fn(should_abort, budget_ms: int) -> JobStepResult:
            self._stats.last_idle_run = time.time()
            started = time.monotonic()
            idle_stats = None
            done = True
            ts_utc = datetime.now(timezone.utc).isoformat()
            try:
                if hasattr(processor, "process_step"):
                    result = processor.process_step(
                        should_abort=should_abort,
                        budget_ms=budget_ms,
                        persist_checkpoint=True,
                    )
                    if isinstance(result, tuple):
                        done = bool(result[0])
                        idle_stats = result[1] if len(result) > 1 else None
                    else:
                        done = bool(result)
                else:
                    if hasattr(processor, "process"):
                        try:
                            processor.process(should_abort=should_abort)
                        except TypeError:
                            processor.process()
                    done = True
            except Exception as exc:
                consumed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
                self._stats.last_idle_error = str(exc)
                self._stats.last_idle_error_ts = time.time()
                record_telemetry(
                    "processing.idle",
                    {"ts_utc": ts_utc, "done": False, "consumed_ms": consumed_ms, "error": str(exc)},
                )
                return JobStepResult(done=False, consumed_ms=consumed_ms)
            consumed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
            payload = {"ts_utc": ts_utc, "done": bool(done), "consumed_ms": consumed_ms}
            stats_payload = None
            if isinstance(idle_stats, dict):
                stats_payload = dict(idle_stats)
            elif idle_stats is not None and hasattr(idle_stats, "__dataclass_fields__"):
                stats_payload = asdict(idle_stats)
            if stats_payload is not None:
                self._stats.last_idle_stats = dict(stats_payload)
                processed = int(stats_payload.get("processed", 0) or 0)
                if processed > 0:
                    self._stats.last_idle_ok = time.time()
                errors = int(stats_payload.get("errors", 0) or 0)
                if errors > 0:
                    self._stats.last_idle_error = "idle_errors"
                    self._stats.last_idle_error_ts = time.time()
                payload.update(stats_payload)
            record_telemetry("processing.idle", payload)
            return JobStepResult(done=done, consumed_ms=consumed_ms)

        estimate_ms = int(idle_cfg.get("estimate_ms", 2000))
        self._scheduler.enqueue(
            Job(
                name="idle.extract",
                step_fn=step_fn,
                heavy=True,
                estimated_ms=estimate_ms,
                gpu_heavy=True,
                payload={"task": "idle.extract"},
            )
        )
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
        self._scheduler.enqueue(
            Job(
                name="idle.research",
                step_fn=step_fn,
                heavy=True,
                estimated_ms=estimate_ms,
                gpu_heavy=True,
                payload={"task": "idle.research"},
            )
        )
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

    def _schedule_storage_retention(self) -> None:
        if self._retention_monitor is None:
            return
        if not self._retention_monitor.due():
            return
        if "storage.retention" in self._queued:
            return

        def job_fn():
            result = self._retention_monitor.record()
            if result is not None:
                self._stats.last_retention_run = time.time()

        self._scheduler.enqueue(Job(name="storage.retention", fn=job_fn, heavy=True, estimated_ms=500))
        self._queued.add("storage.retention")

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

    def _watchdog_payload(self, signals: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config.get("processing", {}).get("watchdog", {}) if isinstance(self._config, dict) else {}
        idle_cfg = self._config.get("processing", {}).get("idle", {}) if isinstance(self._config, dict) else {}
        enabled = bool(cfg.get("enabled", True))
        idle_enabled = bool(idle_cfg.get("enabled", True))
        stall_seconds = int(cfg.get("stall_seconds", 300))
        min_idle_seconds = int(cfg.get("min_idle_seconds", 0))
        stats = self._scheduler.last_stats()
        now = time.time()

        def _iso(ts: float | None) -> str | None:
            if ts is None:
                return None
            return datetime.fromtimestamp(ts, timezone.utc).isoformat()

        payload = {
            "enabled": bool(enabled and idle_enabled),
            "state": "disabled",
            "reason": None,
            "stall_seconds": stall_seconds,
            "min_idle_seconds": min_idle_seconds,
            "idle_seconds": float(signals.get("idle_seconds", 0.0)),
            "user_active": bool(signals.get("user_active", False)),
            "last_idle_run_ts": _iso(self._stats.last_idle_run),
            "last_idle_ok_ts": _iso(self._stats.last_idle_ok),
            "last_idle_error_ts": _iso(self._stats.last_idle_error_ts),
            "last_idle_error": self._stats.last_idle_error,
        }
        if not enabled or not idle_enabled:
            payload["state"] = "disabled"
            payload["reason"] = "idle_disabled"
            return payload
        if payload["user_active"] or payload["idle_seconds"] < min_idle_seconds:
            payload["state"] = "paused"
            payload["reason"] = "active_user" if payload["user_active"] else "idle_short"
            return payload
        if not bool(stats.heavy_allowed) or stats.mode == "ACTIVE_CAPTURE_ONLY":
            payload["state"] = "paused"
            payload["reason"] = stats.reason or "governor_block"
            return payload
        if self._stats.last_idle_error_ts and (
            self._stats.last_idle_ok is None or self._stats.last_idle_error_ts > self._stats.last_idle_ok
        ):
            age = max(0.0, now - self._stats.last_idle_error_ts)
            payload["state"] = "error"
            payload["reason"] = "idle_error"
            payload["age_seconds"] = age
            return payload
        if self._stats.last_idle_run is None:
            payload["state"] = "pending"
            payload["reason"] = "no_idle_runs"
            return payload
        age = max(0.0, now - self._stats.last_idle_run)
        payload["age_seconds"] = age
        if age >= stall_seconds:
            payload["state"] = "stalled"
            payload["reason"] = "no_idle_heartbeat"
        else:
            payload["state"] = "ok"
        return payload

    def _maybe_emit_watchdog_event(self, watchdog: dict[str, Any]) -> None:
        if self._events is None or not isinstance(watchdog, dict):
            return
        state = watchdog.get("state")
        if not state:
            return
        now = time.time()
        event_type = None
        if state in {"stalled", "error"}:
            throttle_s = max(60, int(watchdog.get("stall_seconds", 300) or 300))
            if (
                self._last_watchdog_state == state
                and self._last_watchdog_event_ts is not None
                and (now - self._last_watchdog_event_ts) < throttle_s
            ):
                return
            event_type = f"processing.watchdog.{state}"
        elif state == "ok" and self._last_watchdog_state in {"stalled", "error"}:
            event_type = "processing.watchdog.restore"

        self._last_watchdog_state = state
        if not event_type:
            return

        payload = dict(watchdog)
        payload["event"] = event_type
        ts_utc = datetime.now(timezone.utc).isoformat()
        try:
            self._events.journal_event(event_type, payload, ts_utc=ts_utc)
        except Exception:
            pass
        self._last_watchdog_event_ts = now

    def _emit_telemetry(self, signals: dict[str, Any], executed: list[str], watchdog: dict[str, Any]) -> None:
        record_telemetry("processing.watchdog", watchdog)
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
            "fullscreen": bool(signals.get("fullscreen_active", False)),
            "gpu_guard": self._gpu_guard_snapshot,
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
                "ran_gpu_only": int(getattr(stats, "ran_gpu_only", 0) or 0),
            },
            "executed": list(executed),
            "watchdog": watchdog,
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

    def _handle_mode_transitions(self, stats: Any) -> None:
        runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
        enforcement = runtime_cfg.get("mode_enforcement", {}) if isinstance(runtime_cfg, dict) else {}
        suspend_deadline_ms = int(enforcement.get("suspend_deadline_ms", 500) or 500)
        resume_budget_ms = int(enforcement.get("idle_resume_budget_ms", 3000) or 3000)
        mode = getattr(stats, "mode", None)
        if mode is None:
            return
        now = time.monotonic()
        if self._stats.last_mode != mode:
            self._stats.last_mode = mode
            if mode == "ACTIVE_CAPTURE_ONLY":
                self._suspend_requested_at = now
                self._resume_requested_at = None
                self._suspend_acked = False
            elif mode == "IDLE_DRAIN":
                self._resume_requested_at = now
                self._suspend_requested_at = None
                self._resume_acked = False
            append_audit_event(
                action="runtime.mode_change",
                actor="runtime.conductor",
                outcome="ok",
                details={"mode": mode, "reason": getattr(stats, "reason", None)},
            )
        if mode == "ACTIVE_CAPTURE_ONLY" and self._suspend_requested_at is not None:
            elapsed_ms = int(max(0.0, (now - self._suspend_requested_at) * 1000.0))
            inflight = int(getattr(stats, "inflight_heavy", 0) or 0)
            if not self._suspend_acked and inflight == 0:
                self._suspend_acked = True
                append_audit_event(
                    action="runtime.suspend_ack",
                    actor="runtime.scheduler",
                    outcome="ok",
                    details={"elapsed_ms": elapsed_ms},
                )
            if suspend_deadline_ms and elapsed_ms > suspend_deadline_ms and inflight > 0:
                removed = 0
                if hasattr(self._scheduler, "force_stop"):
                    removed = int(self._scheduler.force_stop("active_suspend_deadline"))
                append_audit_event(
                    action="runtime.force_stop",
                    actor="runtime.scheduler",
                    outcome="ok" if removed > 0 else "noop",
                    details={"elapsed_ms": elapsed_ms, "removed_jobs": removed},
                )
        if mode == "IDLE_DRAIN" and self._resume_requested_at is not None:
            elapsed_ms = int(max(0.0, (now - self._resume_requested_at) * 1000.0))
            admitted = int(getattr(stats, "admitted_heavy", 0) or 0)
            if not self._resume_acked and admitted > 0:
                self._resume_acked = True
                append_audit_event(
                    action="runtime.resume_ack",
                    actor="runtime.scheduler",
                    outcome="ok",
                    details={"elapsed_ms": elapsed_ms},
                )
            if resume_budget_ms and elapsed_ms > resume_budget_ms and not self._resume_acked:
                append_audit_event(
                    action="runtime.resume_late",
                    actor="runtime.scheduler",
                    outcome="warn",
                    details={"elapsed_ms": elapsed_ms, "budget_ms": resume_budget_ms},
                )

    def _maybe_release_gpu(self, signals: dict[str, Any], mode: str) -> None:
        runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
        gpu_cfg = runtime_cfg.get("gpu", {}) if isinstance(runtime_cfg, dict) else {}
        if not isinstance(gpu_cfg, dict) or not bool(gpu_cfg.get("release_vram_on_active", True)):
            return
        if not bool(signals.get("user_active", False)):
            return
        deadline_ms = int(gpu_cfg.get("release_vram_deadline_ms", 250) or 0)
        if deadline_ms <= 0:
            deadline_ms = 250
        now = time.monotonic()
        if self._last_gpu_release_ts is not None and (now - self._last_gpu_release_ts) < (deadline_ms / 1000.0):
            return
        result = release_vram(reason="user_active")
        self._last_gpu_release_ts = now
        payload = {
            "event": "gpu.release",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "mode": str(mode),
            "user_active": True,
            "result": result,
        }
        record_telemetry("gpu.release", payload)
        if self._events is not None:
            try:
                self._events.journal_event("gpu.release", payload)
            except Exception:
                pass
        if self._logger is not None:
            try:
                self._logger.log("gpu.release", payload)
            except Exception:
                pass

    def _maybe_emit_fullscreen_event(self, signals: dict[str, Any]) -> None:
        fullscreen = bool(signals.get("fullscreen_active", False))
        if self._last_fullscreen_state is None:
            self._last_fullscreen_state = fullscreen
            return
        if fullscreen == self._last_fullscreen_state:
            return
        self._last_fullscreen_state = fullscreen
        snapshot = self._fullscreen_snapshot if isinstance(self._fullscreen_snapshot, dict) else {}
        payload = {
            "event": "runtime.fullscreen_halt" if fullscreen else "runtime.fullscreen_resume",
            "ts_utc": snapshot.get("ts_utc"),
            "fullscreen": fullscreen,
            "reason": snapshot.get("reason"),
            "window": snapshot.get("window"),
        }
        record_telemetry("runtime.fullscreen", payload)
        append_audit_event(
            action=payload["event"],
            actor="runtime.conductor",
            outcome="ok",
            details={k: v for k, v in payload.items() if k != "event"},
        )
        if self._events is not None:
            try:
                self._events.journal_event(payload["event"], payload, ts_utc=snapshot.get("ts_utc"))
            except Exception:
                pass
        if self._logger is not None:
            try:
                self._logger.log("runtime.fullscreen", payload)
            except Exception:
                pass

    def _maybe_emit_gpu_guard_event(self, signals: dict[str, Any]) -> None:
        if self._gpu_guard_snapshot is None:
            return
        ok = bool(self._gpu_guard_snapshot.get("ok", False))
        if self._last_gpu_guard_ok is None:
            self._last_gpu_guard_ok = ok
            return
        if ok == self._last_gpu_guard_ok:
            return
        self._last_gpu_guard_ok = ok
        payload = {
            "event": "runtime.gpu_guard_ok" if ok else "runtime.gpu_guard_blocked",
            "decision": dict(self._gpu_guard_snapshot),
            "gpu_only_allowed": bool(signals.get("gpu_only_allowed", False)),
        }
        record_telemetry("runtime.gpu_guard", payload)
        append_audit_event(
            action=payload["event"],
            actor="runtime.conductor",
            outcome="ok",
            details=payload,
        )
        if self._events is not None:
            try:
                self._events.journal_event(payload["event"], payload)
            except Exception:
                pass

    def _run_once(self, *, force: bool = False) -> list[str]:
        if hasattr(self._scheduler, "update_config"):
            try:
                self._scheduler.update_config(self._config)
            except Exception:
                pass
        signals = self._signals(query_intent=True if force else None)
        fullscreen_active = bool(signals.get("fullscreen_active", False))
        if not fullscreen_active:
            self._schedule_idle()
            self._schedule_research()
            self._schedule_storage_pressure()
            self._schedule_storage_retention()
        executed = self._scheduler.run_pending(signals)
        stats = self._scheduler.last_stats()
        self._handle_mode_transitions(stats)
        self._maybe_emit_fullscreen_event(signals)
        self._maybe_emit_gpu_guard_event(signals)
        self._maybe_release_gpu(signals, stats.mode)
        watchdog = self._watchdog_payload(signals)
        self._stats.last_watchdog = watchdog
        self._maybe_emit_watchdog_event(watchdog)
        self._emit_telemetry(signals, executed, watchdog)
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
                "ran_gpu_only": int(getattr(stats, "ran_gpu_only", 0) or 0),
                "routed_jobs": int(getattr(stats, "routed_jobs", 0) or 0),
                "ts_monotonic": float(stats.ts_monotonic),
            },
            "watchdog": self._stats.last_watchdog,
        }

    def watchdog_state(self) -> dict[str, Any] | None:
        return self._stats.last_watchdog

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
