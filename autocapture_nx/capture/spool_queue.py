"""Queue helper that prefers spooling to disk over dropping or blocking.

Used by capture plugins that must not drop evidence under transient backpressure.
If a bounded in-memory queue is full, we can optionally spool the item to a
durable overflow directory (separate volume) and continue capturing.
"""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class EnqueueDecision:
    queued: bool
    spooled: bool
    waited_ms: int


def enqueue_or_spool(
    q: "queue.Queue[dict[str, Any] | None]",
    item: dict[str, Any],
    *,
    spool_fn: Callable[[], bool] | None = None,
    block_timeout_s: float = 0.5,
) -> EnqueueDecision:
    """Enqueue an item, or spool it if the queue is full.

    - First tries non-blocking enqueue.
    - If the queue is full and spool_fn is provided, calls spool_fn() and returns.
    - Otherwise blocks (with retry) until the item is enqueued (no-loss fallback).
    """
    start = time.perf_counter()
    try:
        q.put_nowait(item)
        return EnqueueDecision(queued=True, spooled=False, waited_ms=0)
    except queue.Full:
        pass

    if spool_fn is not None:
        ok = False
        try:
            ok = bool(spool_fn())
        except Exception:
            ok = False
        if ok:
            waited_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))
            return EnqueueDecision(queued=False, spooled=True, waited_ms=waited_ms)
        # Spooling failed (or was disabled); fall back to blocking enqueue (no-loss).

    # Fail-closed fallback: block instead of dropping evidence.
    while True:
        try:
            q.put(item, timeout=max(0.05, float(block_timeout_s)))
            waited_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))
            return EnqueueDecision(queued=True, spooled=False, waited_ms=waited_ms)
        except queue.Full:
            continue
