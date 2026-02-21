import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autocapture.runtime.conductor import RuntimeConductor
from autocapture.runtime.governor import RuntimeGovernor


class _Tracker:
    def __init__(self, idle_seconds: float) -> None:
        self._idle = idle_seconds

    def idle_seconds(self) -> float:
        return self._idle


class _IdleProcessor:
    def __init__(self) -> None:
        self.called = 0

    def process(self, **_kwargs):
        self.called += 1


class _ResearchRunner:
    def __init__(self) -> None:
        self.called = 0

    def run_once(self):
        self.called += 1
        return {"ok": True}


class _PromptOpsOptimizer:
    def __init__(self, *, due: bool = True) -> None:
        self.called = 0
        self._due = due

    def due(self) -> bool:
        return bool(self._due)

    def run_once(self, *, user_active: bool, idle_seconds: float | None = None, force: bool = False):
        self.called += 1
        return {
            "ok": True,
            "user_active": bool(user_active),
            "idle_seconds": float(idle_seconds or 0.0),
            "force": bool(force),
        }


class _System:
    def __init__(self, config: dict, tracker: _Tracker) -> None:
        self.config = config
        self._tracker = tracker
        self._governor = RuntimeGovernor(idle_window_s=int(config["runtime"]["idle_window_s"]))

    def has(self, name: str) -> bool:
        return name in ("tracking.input", "runtime.governor")

    def get(self, name: str):
        if name == "tracking.input":
            return self._tracker
        if name == "runtime.governor":
            return self._governor
        raise KeyError(name)


class _SystemNoTracker:
    def __init__(self, config: dict) -> None:
        self.config = config
        self._governor = RuntimeGovernor(idle_window_s=int(config["runtime"]["idle_window_s"]))

    def has(self, name: str) -> bool:
        return name in ("runtime.governor",)

    def get(self, name: str):
        if name == "runtime.governor":
            return self._governor
        raise KeyError(name)


class RuntimeConductorTests(unittest.TestCase):
    def test_idle_jobs_only_when_idle(self) -> None:
        config = {
            "runtime": {
                "idle_window_s": 10,
                "active_window_s": 2,
                "mode_enforcement": {"suspend_workers": True},
                "budgets": {
                    "window_s": 600,
                    "window_budget_ms": 8000,
                    "per_job_max_ms": 2500,
                    "max_jobs_per_window": 4,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 10,
                    "allow_heavy_during_active": False,
                    # Keep this unit test focused on idle gating, not host resource noise.
                    "cpu_max_utilization": 1.0,
                    "ram_max_utilization": 1.0,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
            "promptops": {
                "optimizer": {
                    "enabled": True,
                    "interval_s": 300,
                    "estimate_ms": 200,
                }
            },
            "research": {"enabled": True, "run_on_idle": True, "interval_s": 0},
        }
        tracker = _Tracker(idle_seconds=20)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        conductor._idle_processor = _IdleProcessor()
        conductor._promptops_optimizer = _PromptOpsOptimizer(due=True)
        conductor._research_runner = _ResearchRunner()

        executed = conductor._run_once()
        self.assertIn("idle.extract", executed)
        self.assertIn("promptops.optimize", executed)
        self.assertEqual(conductor._promptops_optimizer.called, 1)
        self.assertNotIn("idle.research", executed)
        self.assertEqual(conductor._research_runner.called, 0)

        tracker._idle = 0
        executed = conductor._run_once()
        self.assertNotIn("idle.extract", executed)
        self.assertNotIn("promptops.optimize", executed)
        self.assertEqual(conductor._promptops_optimizer.called, 1)

    def test_idle_budget_job_limit(self) -> None:
        config = {
            "runtime": {
                "idle_window_s": 5,
                "active_window_s": 2,
                "mode_enforcement": {"suspend_workers": True},
                "budgets": {
                    "window_s": 600,
                    "window_budget_ms": 8000,
                    "per_job_max_ms": 2500,
                    "max_jobs_per_window": 1,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 5,
                    "allow_heavy_during_active": False,
                    # Keep this unit test focused on job-window limits, not host resource noise.
                    "cpu_max_utilization": 1.0,
                    "ram_max_utilization": 1.0,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
            "research": {"enabled": False, "run_on_idle": False, "interval_s": 0},
        }
        tracker = _Tracker(idle_seconds=30)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        idle = _IdleProcessor()
        conductor._idle_processor = idle

        conductor._run_once()
        self.assertEqual(idle.called, 1)
        conductor._run_once()
        self.assertEqual(idle.called, 1)

    def test_force_run_sets_user_query_signals_and_executes_idle_extract(self) -> None:
        config = {
            "runtime": {
                "idle_window_s": 10,
                "active_window_s": 2,
                "mode_enforcement": {"suspend_workers": True},
                "budgets": {
                    "window_s": 600,
                    "window_budget_ms": 8000,
                    "per_job_max_ms": 2500,
                    "max_jobs_per_window": 4,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 10,
                    "allow_heavy_during_active": False,
                    "cpu_max_utilization": 1.0,
                    "ram_max_utilization": 1.0,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
        }
        tracker = _Tracker(idle_seconds=0)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        idle = _IdleProcessor()
        conductor._idle_processor = idle

        signals = conductor._signals(query_intent=True)
        self.assertTrue(bool(signals.get("query_intent")))
        self.assertTrue(bool(signals.get("allow_query_heavy")))
        self.assertEqual(conductor._governor.decide(signals).mode, "USER_QUERY")

        executed = conductor._run_once(force=True)
        self.assertIn("idle.extract", executed)
        self.assertEqual(idle.called, 1)

    def test_force_run_respects_allow_query_heavy_disable(self) -> None:
        config = {
            "runtime": {
                "idle_window_s": 10,
                "active_window_s": 2,
                "mode_enforcement": {
                    "suspend_workers": True,
                    "allow_query_heavy": False,
                },
                "budgets": {
                    "window_s": 600,
                    "window_budget_ms": 8000,
                    "per_job_max_ms": 2500,
                    "max_jobs_per_window": 4,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 10,
                    "allow_heavy_during_active": False,
                    "cpu_max_utilization": 1.0,
                    "ram_max_utilization": 1.0,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
        }
        tracker = _Tracker(idle_seconds=0)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        idle = _IdleProcessor()
        conductor._idle_processor = idle

        signals = conductor._signals(query_intent=True)
        self.assertTrue(bool(signals.get("query_intent")))
        self.assertFalse(bool(signals.get("allow_query_heavy")))
        self.assertEqual(conductor._governor.decide(signals).mode, "ACTIVE_CAPTURE_ONLY")

        executed = conductor._run_once(force=True)
        self.assertNotIn("idle.extract", executed)
        self.assertEqual(idle.called, 0)

    def test_missing_sidecar_activity_signal_is_fail_closed_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            signal_path = Path(tmp) / "activity" / "activity_signal.json"
            config = {
                "runtime": {
                    "idle_window_s": 10,
                    "active_window_s": 2,
                    "activity": {
                        "assume_idle_when_missing": True,
                        "sidecar_signal_path": str(signal_path),
                    },
                    "mode_enforcement": {"suspend_workers": True},
                    "budgets": {"min_idle_seconds": 10, "cpu_max_utilization": 1.0, "ram_max_utilization": 1.0},
                },
            }
            conductor = RuntimeConductor(_SystemNoTracker(config))
            signals = conductor._signals()
            self.assertTrue(bool(signals.get("user_active")))
            self.assertEqual(float(signals.get("idle_seconds", 1.0)), 0.0)

    def test_stale_sidecar_activity_signal_is_fail_closed_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            signal_path = Path(tmp) / "activity" / "activity_signal.json"
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text(
                json.dumps(
                    {
                        "ts_utc": (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
                        "idle_seconds": 999.0,
                        "user_active": False,
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "runtime": {
                    "idle_window_s": 10,
                    "active_window_s": 2,
                    "activity": {
                        "assume_idle_when_missing": False,
                        "sidecar_signal_path": str(signal_path),
                        "max_signal_age_s": 5,
                    },
                    "mode_enforcement": {"suspend_workers": True},
                    "budgets": {"min_idle_seconds": 10, "cpu_max_utilization": 1.0, "ram_max_utilization": 1.0},
                },
            }
            conductor = RuntimeConductor(_SystemNoTracker(config))
            signals = conductor._signals()
            self.assertTrue(bool(signals.get("user_active")))
            self.assertEqual(float(signals.get("idle_seconds", 1.0)), 0.0)


if __name__ == "__main__":
    unittest.main()
