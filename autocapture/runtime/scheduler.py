"""Simple scheduler honoring RuntimeGovernor decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from autocapture.runtime.governor import RuntimeGovernor


@dataclass
class Job:
    name: str
    fn: Callable[[], None]
    heavy: bool = True


class Scheduler:
    def __init__(self, governor: RuntimeGovernor) -> None:
        self._governor = governor
        self._queue: list[Job] = []

    def enqueue(self, job: Job) -> None:
        self._queue.append(job)

    def run_pending(self, signals: dict) -> list[str]:
        decision = self._governor.decide(signals)
        executed: list[str] = []
        if decision.mode == "ACTIVE_CAPTURE_ONLY":
            return executed
        remaining: list[Job] = []
        for job in self._queue:
            if decision.mode in ("USER_QUERY", "IDLE_DRAIN") or not job.heavy:
                job.fn()
                executed.append(job.name)
            else:
                remaining.append(job)
        self._queue = remaining
        return executed
