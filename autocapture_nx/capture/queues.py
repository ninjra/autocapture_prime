"""Bounded queues with explicit drop policies."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import Any


@dataclass
class DropStats:
    dropped: int = 0


class BoundedQueue:
    def __init__(self, maxsize: int, drop_policy: str) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=max(0, int(maxsize)))
        self._drop_policy = drop_policy
        self.stats = DropStats()

    def qsize(self) -> int:
        return self._queue.qsize()

    def put(self, item: Any) -> bool:
        if self._queue.maxsize <= 0:
            self._queue.put(item)
            return True
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            if self._drop_policy == "drop_oldest":
                try:
                    _ = self._queue.get_nowait()
                except queue.Empty:
                    self.stats.dropped += 1
                    return False
                self.stats.dropped += 1
                try:
                    self._queue.put_nowait(item)
                    return True
                except queue.Full:
                    self.stats.dropped += 1
                    return False
            if self._drop_policy == "drop_newest":
                self.stats.dropped += 1
                return False
            # block policy
            self._queue.put(item)
            return True

    def get(self, timeout: float | None = None) -> Any:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        try:
            self._queue.task_done()
        except ValueError:
            return
