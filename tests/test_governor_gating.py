import unittest
from unittest.mock import patch

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Scheduler, Job, JobStepResult


class GovernorGatingTests(unittest.TestCase):
    def test_governor_modes(self) -> None:
        governor = RuntimeGovernor(idle_window_s=10)
        self.assertEqual(governor.decide({"user_active": True, "idle_seconds": 1, "query_intent": False}).mode, "ACTIVE_CAPTURE_ONLY")
        self.assertEqual(governor.decide({"user_active": False, "idle_seconds": 15, "query_intent": False}).mode, "IDLE_DRAIN")
        self.assertEqual(governor.decide({"user_active": False, "idle_seconds": 1, "query_intent": True}).mode, "USER_QUERY")

    def test_scheduler_respects_modes(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran = []
        scheduler.enqueue(Job(name="heavy", fn=lambda: ran.append("heavy"), heavy=True))
        scheduler.enqueue(Job(name="light", fn=lambda: ran.append("light"), heavy=False))

        scheduler.run_pending({"user_active": True, "idle_seconds": 1, "query_intent": False})
        self.assertEqual(ran, [])

        scheduler.run_pending({"user_active": False, "idle_seconds": 10, "query_intent": False})
        self.assertEqual(ran, ["heavy", "light"])

    def test_idle_budget_exhaustion_defers_heavy(self) -> None:
        governor = RuntimeGovernor(idle_window_s=1)
        governor.update_config(
            {
                "runtime": {
                    "idle_window_s": 1,
                    "mode_enforcement": {"suspend_workers": True},
                    "budgets": {
                        "window_s": 60,
                        "window_budget_ms": 40,
                        "per_job_max_ms": 40,
                        "max_jobs_per_window": 10,
                        "max_heavy_concurrency": 1,
                        "preempt_grace_ms": 0,
                        "min_idle_seconds": 1,
                        "allow_heavy_during_active": False,
                    },
                }
            }
        )
        scheduler = Scheduler(governor)
        ran: list[str] = []

        def heavy_step(_should_abort, _budget_ms):
            ran.append("heavy")
            return JobStepResult(done=True, consumed_ms=40)

        scheduler.enqueue(Job(name="heavy", step_fn=heavy_step, heavy=True, estimated_ms=40))
        scheduler.run_pending({"user_active": False, "idle_seconds": 10, "query_intent": False})
        self.assertEqual(ran, ["heavy"])

        scheduler.enqueue(Job(name="heavy2", step_fn=heavy_step, heavy=True, estimated_ms=40))
        scheduler.run_pending({"user_active": False, "idle_seconds": 10, "query_intent": False})
        self.assertEqual(ran, ["heavy"])

    def test_user_query_allows_heavy_even_when_active(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran: list[str] = []
        scheduler.enqueue(Job(name="heavy", fn=lambda: ran.append("heavy"), heavy=True))

        scheduler.run_pending({"user_active": True, "idle_seconds": 0, "query_intent": True})
        self.assertEqual(ran, ["heavy"])

    def test_user_query_respects_allow_query_heavy_gate(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran: list[str] = []
        scheduler.enqueue(Job(name="heavy", fn=lambda: ran.append("heavy"), heavy=True))

        signals = {
            "user_active": True,
            "idle_seconds": 0,
            "query_intent": True,
            "allow_query_heavy": False,
        }
        scheduler.run_pending(signals)
        self.assertEqual(ran, [])
        self.assertEqual(governor.decide(signals).mode, "ACTIVE_CAPTURE_ONLY")

    def test_user_query_does_not_preempt_by_mode(self) -> None:
        governor = RuntimeGovernor(idle_window_s=1)
        governor.decide({"user_active": True, "idle_seconds": 0, "query_intent": True})
        governor._mode_changed_at -= 1.0  # simulate elapsed > preempt grace
        self.assertFalse(governor.should_preempt({"user_active": True, "idle_seconds": 0, "query_intent": True}))

    def test_preempt_immediate_on_activity_when_configured(self) -> None:
        governor = RuntimeGovernor(idle_window_s=1)
        governor.update_config(
            {
                "runtime": {
                    "idle_window_s": 1,
                    "mode_enforcement": {"suspend_workers": True},
                    "budgets": {
                        "window_s": 60,
                        "window_budget_ms": 1000,
                        "per_job_max_ms": 1000,
                        "max_jobs_per_window": 10,
                        "max_heavy_concurrency": 1,
                        "preempt_grace_ms": 0,
                        "min_idle_seconds": 1,
                        "allow_heavy_during_active": False,
                    },
                }
            }
        )
        self.assertFalse(governor.should_preempt({"user_active": False, "idle_seconds": 10}))
        self.assertTrue(governor.should_preempt({"user_active": True, "idle_seconds": 0}))

    def test_suspend_deadline_overrides_preempt_grace(self) -> None:
        governor = RuntimeGovernor(idle_window_s=1)
        governor.update_config(
            {
                "runtime": {
                    "idle_window_s": 1,
                    "mode_enforcement": {"suspend_workers": True, "suspend_deadline_ms": 50},
                    "budgets": {
                        "window_s": 60,
                        "window_budget_ms": 1000,
                        "per_job_max_ms": 1000,
                        "max_jobs_per_window": 10,
                        "max_heavy_concurrency": 1,
                        "preempt_grace_ms": 1000,
                        "min_idle_seconds": 1,
                        "allow_heavy_during_active": False,
                    },
                }
            }
        )
        with patch("autocapture.runtime.governor.time.monotonic", side_effect=[0.0, 0.0, 0.06]):
            governor.decide({"user_active": True, "idle_seconds": 0, "query_intent": False})
            self.assertTrue(governor.should_preempt({"user_active": True, "idle_seconds": 0}))


if __name__ == "__main__":
    unittest.main()
