from __future__ import annotations

import time
from pathlib import Path

from autocapture_nx.capture.overflow_spool import OverflowSpool, OverflowSpoolConfig


def test_overflow_spool_write_and_drain(tmp_path: Path) -> None:
    cfg = OverflowSpoolConfig(enabled=True, root=str(tmp_path / "overflow"), drain_interval_s=0.0, max_drain_per_tick=10)
    spool = OverflowSpool(cfg)
    spool.ensure_dirs()

    drained: list[str] = []

    def drain_fn(meta: dict, blob: bytes) -> bool:
        drained.append(str(meta.get("record_id") or ""))
        assert blob == b"png-bytes"
        return True

    spool.write_item(record_id="run/frame/1", payload={"record_type": "evidence.capture.frame", "ts_utc": "t"}, blob=b"png-bytes", blob_ext="png")
    assert spool.pending_count() == 1

    stats = spool.drain_if_due(now=time.monotonic(), drain_fn=drain_fn)
    assert int(stats["drained"]) == 1
    assert spool.pending_count() == 0
    assert drained == ["run/frame/1"]
