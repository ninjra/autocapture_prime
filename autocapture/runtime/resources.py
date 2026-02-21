"""Runtime resource sampling helpers."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_utilization: float | None
    ram_utilization: float | None
    ts_monotonic: float


def _clamp_fraction(value: Any) -> float | None:
    try:
        num = float(value)
    except Exception:
        return None
    if num < 0:
        return 0.0
    if num > 1:
        return 1.0
    return num


def sample_resources() -> ResourceSnapshot:
    ts = time.monotonic()
    if psutil is None:
        return ResourceSnapshot(cpu_utilization=None, ram_utilization=None, ts_monotonic=ts)
    try:
        cpu = psutil.cpu_percent(interval=None) / 100.0
        mem = psutil.virtual_memory().percent / 100.0
    except Exception:
        return ResourceSnapshot(cpu_utilization=None, ram_utilization=None, ts_monotonic=ts)
    return ResourceSnapshot(
        cpu_utilization=_clamp_fraction(cpu),
        ram_utilization=_clamp_fraction(mem),
        ts_monotonic=ts,
    )
