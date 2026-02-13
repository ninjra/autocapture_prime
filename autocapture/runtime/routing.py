"""Routing decisions for CPU vs WSL2/GPU execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture.runtime.wsl2_queue import Wsl2DispatchResult, Wsl2Queue


@dataclass(frozen=True)
class RoutingDecision:
    target: str
    ok: bool
    allow_fallback: bool
    dispatch: Wsl2DispatchResult | None = None
    reason: str | None = None


def route_gpu_heavy_job(
    *,
    config: dict[str, Any],
    queue: Wsl2Queue,
    job_name: str,
    payload: dict[str, Any],
    run_id: str,
    allow_fallback: bool = True,
) -> RoutingDecision:
    """Route a job based on config flags.

    PERF-05: This is gated by explicit config and defaults to local-only.
    """

    gpu_cfg = config.get("gpu_heavy", {}) if isinstance(config, dict) else {}
    target = str(gpu_cfg.get("target", "local") or "local").lower()
    if target != "wsl2":
        return RoutingDecision(target="local", ok=True, allow_fallback=True, reason="disabled")
    dispatch = queue.dispatch(job_name=job_name, payload=payload, run_id=run_id, allow_fallback=allow_fallback)
    if not dispatch.ok:
        return RoutingDecision(
            target="wsl2",
            ok=False,
            allow_fallback=dispatch.allow_fallback,
            dispatch=dispatch,
            reason=str(dispatch.reason),
        )
    return RoutingDecision(target="wsl2", ok=True, allow_fallback=dispatch.allow_fallback, dispatch=dispatch, reason="queued")

