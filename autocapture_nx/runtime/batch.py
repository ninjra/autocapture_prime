"""Batch (DAG-style) processing runner for Mode B sidecar DataRoots.

This runner is processing-only: it never captures. It repeatedly drains idle
processing until completion or until foreground gating / budgets prevent work.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture.runtime.conductor import create_conductor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_file
from autocapture_nx.kernel.loader import _canonicalize_config_for_hash
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.storage.facts_ndjson import append_fact_line


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
    done: bool,
    blocked_reason: str | None,
    loops: int,
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
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return payload


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

    for loop_idx in range(max(1, int(max_loops))):
        signals = conductor._signals()  # pylint: disable=protected-access
        decision = governor.decide(signals)
        if require_idle and decision.mode != "IDLE_DRAIN":
            blocked_reason = decision.reason or decision.mode
            break
        if not decision.heavy_allowed:
            blocked_reason = decision.reason
            break

        lease = governor.lease("batch.idle.extract", int(decision.budget.remaining_ms), heavy=True)
        if not lease.allowed or lease.granted_ms <= 0:
            blocked_reason = "budget_unavailable"
            break

        def _should_abort() -> bool:
            sig = conductor._signals()  # pylint: disable=protected-access
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
        if step_stats:
            snapshot["idle_stats"] = step_stats
        loop_stats.append(snapshot)
        if step_done:
            done = True
            break
        if sleep_ms > 0:
            time.sleep(max(0.01, min(5.0, float(sleep_ms) / 1000.0)))

    manifest = _build_landscape_manifest(
        config,
        stats=loop_stats,
        done=done,
        blocked_reason=blocked_reason,
        loops=len(loop_stats),
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
        "loops": len(loop_stats),
        "manifest": manifest,
        "steps": loop_stats,
    }

