import unittest

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Scheduler, Job


class RuntimeBudgetTests(unittest.TestCase):
    def test_gpu_only_job_runs_when_allowed(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran: list[str] = []
        scheduler.enqueue(Job(name="gpu_only", fn=lambda: ran.append("gpu"), heavy=True, gpu_only=True))
        scheduler.run_pending(
            {
                "user_active": True,
                "idle_seconds": 0,
                "query_intent": False,
                "gpu_only_allowed": True,
            }
        )
        self.assertEqual(ran, ["gpu"])

    def test_gpu_only_job_deferred_when_not_allowed(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran: list[str] = []
        scheduler.enqueue(Job(name="gpu_only", fn=lambda: ran.append("gpu"), heavy=True, gpu_only=True))
        scheduler.run_pending(
            {
                "user_active": True,
                "idle_seconds": 0,
                "query_intent": False,
                "gpu_only_allowed": False,
            }
        )
        self.assertEqual(ran, [])

    def test_non_gpu_job_blocked_during_active(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran: list[str] = []
        scheduler.enqueue(Job(name="cpu_heavy", fn=lambda: ran.append("cpu"), heavy=True))
        scheduler.run_pending(
            {
                "user_active": True,
                "idle_seconds": 0,
                "query_intent": False,
                "gpu_only_allowed": True,
            }
        )
        self.assertEqual(ran, [])


if __name__ == "__main__":
    unittest.main()
