"""GPU utilization monitor (NVML optional)."""

from __future__ import annotations

import time
from dataclasses import dataclass

try:
    import pynvml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pynvml = None  # type: ignore

_NVML_READY = False


@dataclass(frozen=True)
class GpuSnapshot:
    utilization: float | None
    mem_utilization: float | None
    mem_used_mb: int | None
    mem_total_mb: int | None
    temperature_c: int | None
    ts_monotonic: float


def _ensure_nvml() -> bool:
    global _NVML_READY
    if _NVML_READY:
        return True
    if pynvml is None:
        return False
    try:
        pynvml.nvmlInit()
        _NVML_READY = True
        return True
    except Exception:
        return False


def _clamp_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return float(value)


def sample_gpu(index: int = 0) -> GpuSnapshot:
    ts = time.monotonic()
    if not _ensure_nvml():
        return GpuSnapshot(
            utilization=None,
            mem_utilization=None,
            mem_used_mb=None,
            mem_total_mb=None,
            temperature_c=None,
            ts_monotonic=ts,
        )
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(int(index))
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        util_gpu = _clamp_fraction(util.gpu / 100.0)
        mem_util = _clamp_fraction(mem.used / mem.total if mem.total else None)
        return GpuSnapshot(
            utilization=util_gpu,
            mem_utilization=mem_util,
            mem_used_mb=int(mem.used // (1024 * 1024)),
            mem_total_mb=int(mem.total // (1024 * 1024)),
            temperature_c=int(temp),
            ts_monotonic=ts,
        )
    except Exception:
        return GpuSnapshot(
            utilization=None,
            mem_utilization=None,
            mem_used_mb=None,
            mem_total_mb=None,
            temperature_c=None,
            ts_monotonic=ts,
        )
