from __future__ import annotations

import queue

from autocapture_nx.capture.spool_queue import enqueue_or_spool


def test_enqueue_or_spool_prefers_spool_when_full() -> None:
    q: "queue.Queue[dict | None]" = queue.Queue(maxsize=1)
    q.put_nowait({"x": 1})

    called = {"ok": 0}

    def spool_fn() -> bool:
        called["ok"] += 1
        return True

    decision = enqueue_or_spool(q, {"x": 2}, spool_fn=spool_fn, block_timeout_s=0.01)
    assert decision.queued is False
    assert decision.spooled is True
    assert called["ok"] == 1


def test_enqueue_or_spool_blocks_when_full_and_no_spool() -> None:
    q: "queue.Queue[dict | None]" = queue.Queue(maxsize=1)
    q.put_nowait({"x": 1})
    # Remove the item so the next enqueue can succeed immediately.
    q.get_nowait()
    decision = enqueue_or_spool(q, {"x": 2}, spool_fn=None, block_timeout_s=0.01)
    assert decision.queued is True
    assert decision.spooled is False
