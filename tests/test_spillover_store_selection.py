from __future__ import annotations

from dataclasses import dataclass

from autocapture_nx.storage.spillover import SpilloverStore


@dataclass(frozen=True)
class _Decision:
    level: str
    free_bytes: int = 0
    free_gb: int = 0
    total_bytes: int = 0
    used_bytes: int = 0
    warn_free_gb: int = 0
    soft_free_gb: int = 0
    critical_free_gb: int = 0
    watermark_soft_mb: int = 0
    watermark_hard_mb: int = 0
    hard_halt: bool = False


class _MemStore:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def put_new(self, record_id: str, data: bytes, *, ts_utc=None, fsync_policy=None) -> None:
        self.writes.append(record_id)

    def get(self, record_id: str, default=None):
        return default

    def exists(self, record_id: str) -> bool:
        return False

    def count(self) -> int:
        return 0


def test_spillover_routes_write_when_primary_soft() -> None:
    primary = _MemStore()
    spill = _MemStore()
    config = {"storage": {"spillover": {"enabled": True, "on_level": "soft"}}}

    def pressure(_cfg, path: str):
        # Primary is soft, spill is ok.
        return _Decision(level="soft") if path == "primary" else _Decision(level="ok")

    store = SpilloverStore(config=config, stores=[("primary", primary), ("spill", spill)], pressure_fn=pressure)
    store.put_new("rid1", b"x", ts_utc="t0")
    assert primary.writes == []
    assert spill.writes == ["rid1"]


def test_spillover_keeps_primary_when_below_trigger() -> None:
    primary = _MemStore()
    spill = _MemStore()
    config = {"storage": {"spillover": {"enabled": True, "on_level": "critical"}}}

    def pressure(_cfg, path: str):
        # Primary is soft but trigger is critical, so stick to primary.
        return _Decision(level="soft") if path == "primary" else _Decision(level="ok")

    store = SpilloverStore(config=config, stores=[("primary", primary), ("spill", spill)], pressure_fn=pressure)
    store.put_new("rid2", b"x", ts_utc="t0")
    assert primary.writes == ["rid2"]
    assert spill.writes == []
