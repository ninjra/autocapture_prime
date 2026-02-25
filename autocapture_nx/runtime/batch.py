"""Batch (DAG-style) processing runner for Mode B sidecar DataRoots.

This runner is processing-only: it never captures. It repeatedly drains idle
processing until completion or until foreground gating / budgets prevent work.
"""

from __future__ import annotations

import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture.runtime.budgets import resolve_idle_budgets
from autocapture.runtime.conductor import create_conductor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture_nx.ingest.handoff_ingest import auto_drain_handoff_spool
from autocapture_nx.kernel.db_status import metadata_db_stability_snapshot
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_file
from autocapture_nx.kernel.loader import _canonicalize_config_for_hash
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.storage.facts_ndjson import append_fact_line


def _canonical_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonical_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_canonical_safe(v) for v in value]
    if isinstance(value, float):
        # Canonical JSON forbids floats; keep metric fidelity by stringifying.
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
        # NaN guard
        if value != value:  # noqa: PLR0124
            return "nan"
        return f"{value:.6f}"
    return value


def _resolve_plugin_locks_path(config: dict[str, Any]) -> Path:
    locks_cfg = config.get("plugins", {}).get("locks", {}) if isinstance(config, dict) else {}
    lockfile = "config/plugin_locks.json"
    if isinstance(locks_cfg, dict):
        lockfile = str(locks_cfg.get("lockfile", lockfile) or lockfile)
    return Path(lockfile)


def _build_landscape_manifest(
    config: dict[str, Any],
    *,
    stats: list[dict[str, Any]],
    sla: dict[str, Any] | None,
    done: bool,
    blocked_reason: str | None,
    loops: int,
    metadata_db_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_hash = sha256_canonical(_canonicalize_config_for_hash(config if isinstance(config, dict) else {}))
    contracts_hash = None
    try:
        contracts_hash = sha256_file("contracts/lock.json")
    except Exception:
        contracts_hash = None
    plugins_hash = None
    try:
        lock_path = _resolve_plugin_locks_path(config)
        if lock_path.exists():
            plugins_hash = sha256_file(lock_path)
    except Exception:
        plugins_hash = None

    run_id = str(config.get("runtime", {}).get("run_id") or "run")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "derived.landscape.manifest",
        "run_id": run_id,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "effective_config_sha256": config_hash,
        "contracts_lock_sha256": contracts_hash or "",
        "plugin_locks_sha256": plugins_hash or "",
        "done": bool(done),
        "blocked_reason": str(blocked_reason or ""),
        "loops": int(max(0, loops)),
        "steps": list(stats),
    }
    if isinstance(sla, dict):
        payload["sla"] = dict(sla)
    if isinstance(metadata_db_guard, dict):
        payload["metadata_db_guard"] = dict(metadata_db_guard)
    payload["slo_alerts"] = _derive_slo_alerts(sla=sla, metadata_db_guard=metadata_db_guard)
    payload = _canonical_safe(payload)
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return payload


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number < 0.0:
        return None
    return number


def _clamp_int(value: Any, *, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(fallback)
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _clamp_float(value: Any, *, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(fallback)
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _apply_adaptive_idle_parallelism(
    config: dict[str, Any],
    *,
    signals: dict[str, Any],
    recent_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    processing_cfg = config.get("processing")
    if not isinstance(processing_cfg, dict):
        return None
    idle_cfg = processing_cfg.get("idle")
    if not isinstance(idle_cfg, dict):
        return None

    adaptive_cfg = idle_cfg.get("adaptive_parallelism")
    if adaptive_cfg is None:
        adaptive_cfg = {}
    if not isinstance(adaptive_cfg, dict):
        return None
    if not bool(adaptive_cfg.get("enabled", False)):
        return None

    budgets = resolve_idle_budgets(config)
    cpu_limit = float(budgets.cpu_max_utilization or 0.5)
    ram_limit = float(budgets.ram_max_utilization or 0.5)
    if cpu_limit <= 0.0:
        cpu_limit = 0.5
    if ram_limit <= 0.0:
        ram_limit = 0.5

    current_cpu = max(1, int(idle_cfg.get("max_concurrency_cpu", 1) or 1))
    current_batch = max(1, int(idle_cfg.get("batch_size", 1) or 1))
    current_items = max(1, int(idle_cfg.get("max_items_per_run", 20) or 1))

    cpu_min = _clamp_int(adaptive_cfg.get("cpu_min", 1), minimum=1, maximum=64, fallback=1)
    cpu_max_default = max(current_cpu, 4)
    cpu_max = _clamp_int(adaptive_cfg.get("cpu_max", cpu_max_default), minimum=cpu_min, maximum=64, fallback=cpu_max_default)
    cpu_step_up = _clamp_int(adaptive_cfg.get("cpu_step_up", 1), minimum=1, maximum=8, fallback=1)
    cpu_step_down = _clamp_int(adaptive_cfg.get("cpu_step_down", 1), minimum=1, maximum=8, fallback=1)

    batch_per_worker = _clamp_int(adaptive_cfg.get("batch_per_worker", 3), minimum=1, maximum=16, fallback=3)
    items_per_worker = _clamp_int(adaptive_cfg.get("items_per_worker", 20), minimum=1, maximum=200, fallback=20)

    batch_min_default = max(1, cpu_min * batch_per_worker)
    batch_max_default = max(current_batch, cpu_max * batch_per_worker)
    batch_min = _clamp_int(
        adaptive_cfg.get("batch_min", batch_min_default),
        minimum=1,
        maximum=2048,
        fallback=batch_min_default,
    )
    batch_max = _clamp_int(
        adaptive_cfg.get("batch_max", batch_max_default),
        minimum=batch_min,
        maximum=2048,
        fallback=batch_max_default,
    )

    items_min_default = max(1, cpu_min * items_per_worker)
    items_max_default = max(current_items, cpu_max * items_per_worker)
    items_min = _clamp_int(
        adaptive_cfg.get("items_min", items_min_default),
        minimum=1,
        maximum=20000,
        fallback=items_min_default,
    )
    items_max = _clamp_int(
        adaptive_cfg.get("items_max", items_max_default),
        minimum=items_min,
        maximum=20000,
        fallback=items_max_default,
    )

    low_watermark = _clamp_float(adaptive_cfg.get("low_watermark", 0.65), minimum=0.05, maximum=0.95, fallback=0.65)
    high_watermark = _clamp_float(adaptive_cfg.get("high_watermark", 0.9), minimum=0.1, maximum=1.5, fallback=0.9)
    if high_watermark <= low_watermark:
        high_watermark = min(1.5, low_watermark + 0.1)
    queue_low = _clamp_int(adaptive_cfg.get("queue_low_watermark", 64), minimum=0, maximum=2_000_000, fallback=64)
    queue_high = _clamp_int(adaptive_cfg.get("queue_high_watermark", 512), minimum=max(1, queue_low + 1), maximum=2_000_000, fallback=512)
    latency_target_ms = _clamp_int(adaptive_cfg.get("latency_p95_target_ms", 1200), minimum=50, maximum=60_000, fallback=1200)
    latency_hard_ms = _clamp_int(adaptive_cfg.get("latency_p95_hard_cap_ms", 4000), minimum=latency_target_ms, maximum=120_000, fallback=4000)

    cpu_util = _to_float(signals.get("cpu_utilization"))
    ram_util = _to_float(signals.get("ram_utilization"))
    ratios = []
    if cpu_util is not None and cpu_limit > 0.0:
        ratios.append(cpu_util / cpu_limit)
    if ram_util is not None and ram_limit > 0.0:
        ratios.append(ram_util / ram_limit)
    pressure_ratio = max(ratios) if ratios else None

    history = [row for row in (recent_steps or []) if isinstance(row, dict)]
    pending_records = 0
    if history:
        latest = history[-1]
        idle_stats_raw = latest.get("idle_stats")
        idle_stats: dict[str, Any] = idle_stats_raw if isinstance(idle_stats_raw, dict) else {}
        pending_records = int(idle_stats.get("pending_records", 0) or 0)
        if pending_records <= 0:
            sla_latest_raw = latest.get("sla")
            sla_latest: dict[str, Any] = sla_latest_raw if isinstance(sla_latest_raw, dict) else {}
            pending_records = int(sla_latest.get("pending_records", 0) or 0)
    consumed_values = [
        int(row.get("consumed_ms", 0) or 0)
        for row in history[-32:]
        if isinstance(row, dict) and int(row.get("consumed_ms", 0) or 0) > 0
    ]
    loop_latency_p95_ms = 0
    if consumed_values:
        ordered = sorted(consumed_values)
        idx = max(0, int(math.ceil(0.95 * float(len(ordered)))) - 1)
        loop_latency_p95_ms = int(ordered[min(idx, len(ordered) - 1)])

    action = "hold"
    reason = "pressure_mid"
    next_cpu = current_cpu
    if pressure_ratio is not None:
        if pressure_ratio >= high_watermark:
            action = "scale_down"
            reason = "pressure_high"
            next_cpu = max(cpu_min, current_cpu - cpu_step_down)
        elif pressure_ratio <= low_watermark:
            action = "scale_up"
            reason = "pressure_low"
            next_cpu = min(cpu_max, current_cpu + cpu_step_up)
    if action == "hold" and loop_latency_p95_ms >= latency_hard_ms and current_cpu > cpu_min:
        action = "scale_down"
        reason = "latency_p95_hard_cap"
        next_cpu = max(cpu_min, current_cpu - max(cpu_step_down, 2))
    elif action == "hold" and loop_latency_p95_ms > latency_target_ms and current_cpu > cpu_min:
        action = "scale_down"
        reason = "latency_p95_target_exceeded"
        next_cpu = max(cpu_min, current_cpu - cpu_step_down)
    elif action == "hold" and pending_records >= queue_high and current_cpu < cpu_max and loop_latency_p95_ms <= latency_target_ms:
        action = "scale_up"
        reason = "queue_high"
        next_cpu = min(cpu_max, current_cpu + cpu_step_up)
    elif (
        action == "hold"
        and bool(history)
        and pending_records <= queue_low
        and current_cpu > cpu_min
        and pressure_ratio is not None
        and pressure_ratio >= low_watermark
    ):
        action = "scale_down"
        reason = "queue_low"
        next_cpu = max(cpu_min, current_cpu - cpu_step_down)
    next_batch = _clamp_int(next_cpu * batch_per_worker, minimum=batch_min, maximum=batch_max, fallback=current_batch)
    next_items = _clamp_int(next_cpu * items_per_worker, minimum=items_min, maximum=items_max, fallback=current_items)

    if next_cpu != current_cpu:
        idle_cfg["max_concurrency_cpu"] = int(next_cpu)
    if next_batch != current_batch:
        idle_cfg["batch_size"] = int(next_batch)
    if next_items != current_items:
        idle_cfg["max_items_per_run"] = int(next_items)

    return {
        "enabled": True,
        "action": action,
        "reason": reason,
        "pressure_ratio": pressure_ratio,
        "cpu_utilization": cpu_util,
        "ram_utilization": ram_util,
        "pending_records": int(pending_records),
        "loop_latency_p95_ms": int(loop_latency_p95_ms),
        "queue_low_watermark": int(queue_low),
        "queue_high_watermark": int(queue_high),
        "latency_p95_target_ms": int(latency_target_ms),
        "latency_p95_hard_cap_ms": int(latency_hard_ms),
        "cpu_limit": cpu_limit,
        "ram_limit": ram_limit,
        "max_concurrency_cpu": int(idle_cfg.get("max_concurrency_cpu", current_cpu)),
        "batch_size": int(idle_cfg.get("batch_size", current_batch)),
        "max_items_per_run": int(idle_cfg.get("max_items_per_run", current_items)),
    }


def _parse_retention_horizon_hours(spec: Any) -> float | None:
    if spec is None:
        return None
    text = str(spec or "").strip().lower()
    if not text or text in {"infinite", "inf", "off", "none", "disabled", "0"}:
        return None
    raw_num = ""
    raw_unit = ""
    for ch in text:
        if ch.isdigit():
            if raw_unit:
                return None
            raw_num += ch
            continue
        if ch.isspace():
            continue
        raw_unit += ch
    if not raw_num:
        return None
    value = float(int(raw_num))
    unit = raw_unit or "d"
    if unit.startswith("h"):
        return value
    if unit.startswith("m"):
        return value / 60.0
    if unit.startswith("s"):
        return value / 3600.0
    return value * 24.0


def _estimate_sla_snapshot(config: dict[str, Any], *, steps: list[dict[str, Any]]) -> dict[str, Any]:
    processing_cfg = config.get("processing", {}) if isinstance(config, dict) else {}
    idle_cfg = processing_cfg.get("idle", {}) if isinstance(processing_cfg, dict) else {}
    sla_cfg = idle_cfg.get("sla_control", {}) if isinstance(idle_cfg.get("sla_control", {}), dict) else {}
    enabled = bool(sla_cfg.get("enabled", True))
    storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
    retention_cfg = storage_cfg.get("retention", {}) if isinstance(storage_cfg, dict) else {}
    retention_horizon_hours = _parse_retention_horizon_hours(retention_cfg.get("evidence"))
    if retention_horizon_hours is None:
        retention_horizon_hours = float(sla_cfg.get("retention_horizon_hours", 144.0) or 144.0)
    warn_ratio = float(sla_cfg.get("lag_warn_ratio", 0.8) or 0.8)
    if warn_ratio <= 0.0:
        warn_ratio = 0.8

    completed_records = 0
    consumed_ms = 0
    pending_records = 0
    latencies_ms: list[int] = []
    for row in steps:
        if not isinstance(row, dict):
            continue
        consumed_ms += int(row.get("consumed_ms", 0) or 0)
        if int(row.get("consumed_ms", 0) or 0) > 0:
            latencies_ms.append(int(row.get("consumed_ms", 0) or 0))
        idle_stats_raw = row.get("idle_stats")
        idle_stats: dict[str, Any] = idle_stats_raw if isinstance(idle_stats_raw, dict) else {}
        completed_records += int(idle_stats.get("records_completed", 0) or 0)
        pending_records = int(idle_stats.get("pending_records", pending_records) or pending_records)

    throughput_records_per_s = 0.0
    if consumed_ms > 0:
        throughput_records_per_s = float(completed_records) / (float(consumed_ms) / 1000.0)
    projected_lag_hours = 0.0
    if pending_records > 0:
        if throughput_records_per_s > 0.0:
            projected_lag_hours = float(pending_records) / throughput_records_per_s / 3600.0
        else:
            projected_lag_hours = float("inf")
    retention_risk = bool(
        enabled
        and pending_records > 0
        and (
            projected_lag_hours == float("inf")
            or projected_lag_hours > float(retention_horizon_hours) * float(warn_ratio)
        )
    )
    latency_p95_ms = 0
    if latencies_ms:
        ordered = sorted(latencies_ms)
        idx = max(0, int(math.ceil(0.95 * float(len(ordered)))) - 1)
        latency_p95_ms = int(ordered[min(idx, len(ordered) - 1)])
    return {
        "enabled": enabled,
        "pending_records": int(pending_records),
        "completed_records": int(completed_records),
        "throughput_records_per_s": throughput_records_per_s,
        "projected_lag_hours": projected_lag_hours,
        "loop_latency_p95_ms": int(latency_p95_ms),
        "retention_horizon_hours": float(retention_horizon_hours),
        "retention_risk": retention_risk,
    }


def _derive_slo_alerts(
    *,
    sla: dict[str, Any] | None,
    metadata_db_guard: dict[str, Any] | None,
) -> list[str]:
    alerts: list[str] = []
    row = sla if isinstance(sla, dict) else {}
    pending_records = int(row.get("pending_records", 0) or 0)
    throughput = float(row.get("throughput_records_per_s", 0.0) or 0.0)
    if bool(row.get("retention_risk", False)):
        alerts.append("retention_risk")
    if pending_records > 0 and throughput <= 0.0:
        alerts.append("throughput_zero_with_backlog")
    if isinstance(metadata_db_guard, dict) and not bool(metadata_db_guard.get("ok", True)):
        alerts.append("metadata_db_unstable")
    return alerts


def _apply_retention_sla_pressure(config: dict[str, Any], *, previous_sla: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(config, dict) or not isinstance(previous_sla, dict):
        return None
    if not bool(previous_sla.get("retention_risk", False)):
        return None
    processing_cfg = config.get("processing", {}) if isinstance(config.get("processing"), dict) else {}
    idle_cfg = processing_cfg.get("idle", {}) if isinstance(processing_cfg.get("idle"), dict) else {}
    sla_cfg = idle_cfg.get("sla_control", {}) if isinstance(idle_cfg.get("sla_control", {}), dict) else {}
    if not bool(sla_cfg.get("enabled", True)):
        return None
    step_up = max(1, int(sla_cfg.get("cpu_step_up_on_risk", 1) or 1))
    current_cpu = max(1, int(idle_cfg.get("max_concurrency_cpu", 1) or 1))
    adaptive_cfg = idle_cfg.get("adaptive_parallelism", {}) if isinstance(idle_cfg.get("adaptive_parallelism", {}), dict) else {}
    cpu_max = max(current_cpu, int(adaptive_cfg.get("cpu_max", max(4, current_cpu)) or max(4, current_cpu)))
    batch_per_worker = max(1, int(adaptive_cfg.get("batch_per_worker", 3) or 3))
    items_per_worker = max(1, int(adaptive_cfg.get("items_per_worker", 20) or 20))

    next_cpu = min(cpu_max, current_cpu + step_up)
    if next_cpu == current_cpu:
        return None
    idle_cfg["max_concurrency_cpu"] = int(next_cpu)
    idle_cfg["batch_size"] = max(1, int(next_cpu * batch_per_worker))
    idle_cfg["max_items_per_run"] = max(1, int(next_cpu * items_per_worker))
    return {
        "action": "sla_scale_up",
        "max_concurrency_cpu": int(next_cpu),
        "batch_size": int(idle_cfg.get("batch_size", 1)),
        "max_items_per_run": int(idle_cfg.get("max_items_per_run", 1)),
    }


def _metadata_db_guard(config: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    processing_cfg = config.get("processing", {}) if isinstance(config.get("processing"), dict) else {}
    idle_cfg = processing_cfg.get("idle", {}) if isinstance(processing_cfg.get("idle"), dict) else {}
    guard_cfg = idle_cfg.get("metadata_db_guard", {})
    if guard_cfg is None:
        guard_cfg = {}
    if not isinstance(guard_cfg, dict):
        return None
    enabled = bool(guard_cfg.get("enabled", True))
    if not enabled:
        return {"enabled": False, "ok": True, "reason": "disabled"}
    sample_count = _clamp_int(guard_cfg.get("sample_count", 3), minimum=1, maximum=32, fallback=3)
    poll_interval_ms = _clamp_int(guard_cfg.get("poll_interval_ms", 150), minimum=0, maximum=2000, fallback=150)
    fail_closed = bool(guard_cfg.get("fail_closed", True))
    snapshot = metadata_db_stability_snapshot(config, sample_count=sample_count, poll_interval_ms=poll_interval_ms)
    stable = snapshot.get("stable")
    exists = bool(snapshot.get("exists", False))
    ok = bool(exists and stable is not False)
    reason = str(snapshot.get("reason") or ("ok" if ok else "metadata_db_unstable_or_missing"))
    return {
        "enabled": True,
        "ok": ok,
        "fail_closed": fail_closed,
        "reason": reason,
        "snapshot": snapshot,
    }


def run_processing_batch(
    system: Any,
    *,
    max_loops: int = 500,
    sleep_ms: int = 200,
    require_idle: bool = True,
) -> dict[str, Any]:
    config = getattr(system, "config", {}) if system is not None else {}
    config = config if isinstance(config, dict) else {}
    conductor = create_conductor(system)
    governor: RuntimeGovernor = getattr(conductor, "_governor", RuntimeGovernor())  # type: ignore[assignment]
    try:
        governor.update_config(config)
    except Exception:
        pass
    processor = IdleProcessor(system)

    loop_stats: list[dict[str, Any]] = []
    done = False
    blocked_reason: str | None = None
    previous_sla: dict[str, Any] | None = None
    metadata_db_guard = _metadata_db_guard(config)
    guard_blocked = bool(
        isinstance(metadata_db_guard, dict)
        and not bool(metadata_db_guard.get("ok", True))
        and bool(metadata_db_guard.get("fail_closed", True))
    )
    if guard_blocked:
        guard_reason = metadata_db_guard.get("reason") if isinstance(metadata_db_guard, dict) else "metadata_db_unstable"
        blocked_reason = str(guard_reason or "metadata_db_unstable")

    for loop_idx in range(max(1, int(max_loops))):
        if guard_blocked:
            break
        signals = conductor._signals()  # pylint: disable=protected-access
        if not require_idle:
            # Manual drain mode (`--no-require-idle`) must be able to run under
            # active-user signals; use the governor's fixture override lane to
            # keep budget enforcement while bypassing idle-mode hard gating.
            if isinstance(signals, dict):
                signals = dict(signals)
            else:
                try:
                    signals = dict(signals)  # type: ignore[arg-type]
                except Exception:
                    signals = {}
            signals["fixture_override"] = True
        sla_pressure = _apply_retention_sla_pressure(config, previous_sla=previous_sla)
        adaptive_idle = _apply_adaptive_idle_parallelism(config, signals=signals, recent_steps=loop_stats)
        decision = governor.decide(signals)
        if require_idle and decision.mode != "IDLE_DRAIN":
            blocked_reason = decision.reason or decision.mode
            break
        if not decision.heavy_allowed:
            blocked_reason = decision.reason
            break

        stage1_handoff = auto_drain_handoff_spool(config)

        lease = governor.lease("batch.idle.extract", int(decision.budget.remaining_ms), heavy=True)
        if not lease.allowed or lease.granted_ms <= 0:
            blocked_reason = "budget_unavailable"
            break

        def _should_abort() -> bool:
            sig = conductor._signals()  # pylint: disable=protected-access
            if not require_idle:
                if isinstance(sig, dict):
                    sig = dict(sig)
                else:
                    try:
                        sig = dict(sig)  # type: ignore[arg-type]
                    except Exception:
                        sig = {}
                sig["fixture_override"] = True
            _ = governor.decide(sig)
            return governor.should_preempt(sig)

        started = time.monotonic()
        step_done = False
        step_stats = None
        try:
            result = processor.process_step(should_abort=_should_abort, budget_ms=lease.granted_ms, persist_checkpoint=True)
            if isinstance(result, tuple):
                step_done = bool(result[0])
                if len(result) > 1 and isinstance(result[1], dict):
                    step_stats = dict(result[1])
                elif len(result) > 1 and hasattr(result[1], "__dataclass_fields__"):
                    try:
                        step_stats = {k: getattr(result[1], k) for k in getattr(result[1], "__dataclass_fields__", {}).keys()}
                    except Exception:
                        step_stats = None
            else:
                step_done = bool(result)
        except Exception as exc:
            step_done = False
            step_stats = {"error": f"{type(exc).__name__}:{exc}"}
        consumed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
        lease.record(consumed_ms)

        snapshot: dict[str, Any] = {
            "loop": int(loop_idx),
            "mode": str(decision.mode),
            "reason": str(decision.reason),
            "budget_granted_ms": int(lease.granted_ms),
            "consumed_ms": int(consumed_ms),
            "done": bool(step_done),
        }
        if adaptive_idle is not None:
            snapshot["adaptive_idle"] = adaptive_idle
        if sla_pressure is not None:
            snapshot["sla_pressure"] = sla_pressure
        if isinstance(stage1_handoff, dict):
            snapshot["stage1_handoff"] = stage1_handoff
        if step_stats:
            snapshot["idle_stats"] = step_stats
        snapshot["sla"] = _estimate_sla_snapshot(config, steps=loop_stats + [snapshot])
        previous_sla = snapshot["sla"] if isinstance(snapshot.get("sla"), dict) else None
        loop_stats.append(snapshot)
        if step_done:
            done = True
            break
        if sleep_ms > 0:
            time.sleep(max(0.01, min(5.0, float(sleep_ms) / 1000.0)))

    sla_snapshot = _estimate_sla_snapshot(config, steps=loop_stats)
    slo_alerts = _derive_slo_alerts(sla=sla_snapshot, metadata_db_guard=metadata_db_guard)
    manifest = _build_landscape_manifest(
        config,
        stats=loop_stats,
        sla=sla_snapshot,
        done=done,
        blocked_reason=blocked_reason,
        loops=len(loop_stats),
        metadata_db_guard=metadata_db_guard,
    )

    # Persist manifest best-effort (append-only).
    try:
        metadata = system.get("storage.metadata") if system is not None and hasattr(system, "get") else None
    except Exception:
        metadata = None
    if metadata is not None and isinstance(manifest, dict):
        run_id = str(manifest.get("run_id") or "run")
        config_hash = str(manifest.get("effective_config_sha256") or "")
        token = (config_hash[:16] if config_hash else "unknown")
        record_id = f"{run_id}/derived.landscape.manifest/{token}"
        try:
            if getattr(metadata, "get", lambda *_args, **_kwargs: None)(record_id) is None:
                if hasattr(metadata, "put_new"):
                    metadata.put_new(record_id, manifest)
                else:
                    metadata.put(record_id, manifest)
        except Exception:
            pass
    try:
        _ = append_fact_line(config, rel_path="landscape_manifests.ndjson", payload=manifest)
    except Exception:
        pass

    return {
        "ok": bool(done),
        "done": bool(done),
        "blocked_reason": blocked_reason,
        "metadata_db_guard": metadata_db_guard,
        "slo_alerts": list(slo_alerts),
        "loops": len(loop_stats),
        "sla": sla_snapshot,
        "manifest": manifest,
        "steps": loop_stats,
    }
