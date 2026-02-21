"""GPU lag guard evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.telemetry import telemetry_snapshot
from autocapture.runtime.gpu_monitor import GpuSnapshot


@dataclass(frozen=True)
class GpuLagGuardDecision:
    ok: bool
    reason: str
    lag_p95_ms: float | None
    queue_p95: float | None
    capture_age_s: float | None
    gpu_utilization: float | None
    gpu_mem_utilization: float | None


def evaluate_gpu_lag_guard(
    config: dict[str, Any],
    *,
    telemetry: dict[str, Any] | None = None,
    gpu: GpuSnapshot | None = None,
) -> GpuLagGuardDecision:
    runtime_cfg = config.get("runtime", {}) if isinstance(config, dict) else {}
    gpu_cfg = runtime_cfg.get("gpu", {}) if isinstance(runtime_cfg, dict) else {}
    guard_cfg = gpu_cfg.get("lag_guard", {}) if isinstance(gpu_cfg, dict) else {}
    enabled = bool(guard_cfg.get("enabled", True))
    if not enabled:
        return GpuLagGuardDecision(
            ok=True,
            reason="disabled",
            lag_p95_ms=None,
            queue_p95=None,
            capture_age_s=None,
            gpu_utilization=None,
            gpu_mem_utilization=None,
        )

    telemetry = telemetry or telemetry_snapshot()
    latest = telemetry.get("latest", {}) if isinstance(telemetry, dict) else {}
    capture = latest.get("capture") if isinstance(latest, dict) else None
    if not isinstance(capture, dict):
        return GpuLagGuardDecision(
            ok=False,
            reason="missing_capture_telemetry",
            lag_p95_ms=None,
            queue_p95=None,
            capture_age_s=None,
            gpu_utilization=getattr(gpu, "utilization", None),
            gpu_mem_utilization=getattr(gpu, "mem_utilization", None),
        )

    lag_p95 = capture.get("lag_p95_ms")
    if lag_p95 is None:
        lag_p95 = capture.get("lag_ms")
    queue_p95 = capture.get("queue_depth_p95")
    if queue_p95 is None:
        queue_p95 = capture.get("queue_depth")
    capture_age = capture.get("last_capture_age_s") or capture.get("last_capture_age_seconds")

    max_lag = float(guard_cfg.get("max_capture_lag_ms", 50) or 0)
    max_queue = float(guard_cfg.get("max_queue_depth_p95", 12) or 0)
    max_age = float(guard_cfg.get("max_capture_age_s", 2.0) or 0)

    if lag_p95 is None:
        return GpuLagGuardDecision(
            ok=False,
            reason="missing_lag",
            lag_p95_ms=None,
            queue_p95=float(queue_p95) if queue_p95 is not None else None,
            capture_age_s=float(capture_age) if capture_age is not None else None,
            gpu_utilization=getattr(gpu, "utilization", None),
            gpu_mem_utilization=getattr(gpu, "mem_utilization", None),
        )
    if max_lag and float(lag_p95) > max_lag:
        return GpuLagGuardDecision(
            ok=False,
            reason="capture_lag",
            lag_p95_ms=float(lag_p95),
            queue_p95=float(queue_p95) if queue_p95 is not None else None,
            capture_age_s=float(capture_age) if capture_age is not None else None,
            gpu_utilization=getattr(gpu, "utilization", None),
            gpu_mem_utilization=getattr(gpu, "mem_utilization", None),
        )
    if queue_p95 is not None and max_queue and float(queue_p95) > max_queue:
        return GpuLagGuardDecision(
            ok=False,
            reason="queue_depth",
            lag_p95_ms=float(lag_p95),
            queue_p95=float(queue_p95),
            capture_age_s=float(capture_age) if capture_age is not None else None,
            gpu_utilization=getattr(gpu, "utilization", None),
            gpu_mem_utilization=getattr(gpu, "mem_utilization", None),
        )
    if capture_age is not None and max_age and float(capture_age) > max_age:
        return GpuLagGuardDecision(
            ok=False,
            reason="capture_age",
            lag_p95_ms=float(lag_p95),
            queue_p95=float(queue_p95) if queue_p95 is not None else None,
            capture_age_s=float(capture_age),
            gpu_utilization=getattr(gpu, "utilization", None),
            gpu_mem_utilization=getattr(gpu, "mem_utilization", None),
        )
    return GpuLagGuardDecision(
        ok=True,
        reason="ok",
        lag_p95_ms=float(lag_p95),
        queue_p95=float(queue_p95) if queue_p95 is not None else None,
        capture_age_s=float(capture_age) if capture_age is not None else None,
        gpu_utilization=getattr(gpu, "utilization", None),
        gpu_mem_utilization=getattr(gpu, "mem_utilization", None),
    )
