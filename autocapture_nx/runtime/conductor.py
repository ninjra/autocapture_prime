"""NX runtime conductor (traceability import path).

The production runtime conductor lives in `autocapture.runtime.conductor`.
This module wraps and augments it with NX-specific persisted artifacts used by
adversarial redesign gates (e.g., pipeline DAG persisted in the state tape).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from autocapture.runtime.conductor import RuntimeConductor as _RuntimeConductor
from autocapture_nx.kernel.state_tape import build_pipeline_dag, persist_pipeline_dag
from autocapture_nx.kernel.telemetry import record_telemetry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RuntimeConductor(_RuntimeConductor):
    """Runtime conductor with persisted pipeline metadata."""

    def __init__(self, system: Any) -> None:
        super().__init__(system)
        self._pipeline_dag_written = False

    def _maybe_persist_pipeline_dag(self) -> None:
        if self._pipeline_dag_written:
            return
        system = getattr(self, "_system", None)
        if system is None or not hasattr(system, "has") or not hasattr(system, "get"):
            return
        if not system.has("storage.metadata"):
            return
        try:
            meta = system.get("storage.metadata")
        except Exception:
            return
        # Use the currently-resolved capabilities as the DAG seed. This is stable
        # under identical config + plugin locks.
        caps: set[str] = set()
        try:
            if hasattr(system, "capabilities"):
                caps = set((system.capabilities.all() or {}).keys())
        except Exception:
            caps = set()
        dag = build_pipeline_dag(enabled_caps=caps)
        run_id = ""
        try:
            cfg = getattr(system, "config", {}) if system is not None else {}
            run_id = str(cfg.get("runtime", {}).get("run_id") or "")
        except Exception:
            run_id = ""
        if not run_id:
            run_id = "run"
        persist_pipeline_dag(meta, run_id=run_id, ts_utc=_utc_now(), dag=dag)
        self._pipeline_dag_written = True

    def start(self) -> None:  # type: ignore[override]
        # Persist pipeline DAG before background loops begin.
        try:
            self._maybe_persist_pipeline_dag()
        except Exception:
            pass
        return super().start()

    def stats(self) -> dict[str, Any]:  # type: ignore[override]
        try:
            base = super().stats()
        except Exception:
            base = {}
        base = dict(base) if isinstance(base, dict) else {}
        base.setdefault("pipeline_dag_persisted", bool(self._pipeline_dag_written))
        return base


def run_job_with_retries(
    *,
    event_builder: Any | None,
    job_name: str,
    fn: Any,
    ts_utc: str | None = None,
    max_attempts: int = 3,
    backoff_s: float = 0.2,
    backoff_max_s: float = 5.0,
    sleep_fn: Any | None = None,
) -> None:
    """Run a job with bounded retries and ledger attempt records.

    This is used by runtime/conductor scheduling to make transient failures
    diagnosable and auditable without silently losing work.
    """

    import time

    name = str(job_name or "").strip() or "job"
    attempts = max(1, int(max_attempts))
    ts = str(ts_utc or _utc_now())
    if sleep_fn is None:
        sleep_fn = time.sleep

    def _ledger(payload: dict[str, Any]) -> None:
        if event_builder is None:
            return
        if not hasattr(event_builder, "ledger_entry"):
            return
        try:
            event_builder.ledger_entry(
                "job.attempt",
                inputs=[],
                outputs=[],
                payload=payload,
                ts_utc=ts,
            )
        except Exception:
            return

    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        start = time.perf_counter()
        ok = True
        err = None
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = f"{type(exc).__name__}: {exc}"
            last_error = err
        elapsed_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))
        payload = {
            "job_name": name,
            "attempt": int(attempt),
            "max_attempts": int(attempts),
            "ok": bool(ok),
            "error": err,
            "elapsed_ms": int(elapsed_ms),
        }
        _ledger(payload)
        try:
            record_telemetry(
                "runtime.job_attempt",
                {"ts_utc": ts, "job_name": name, "attempt": attempt, "ok": ok, "elapsed_ms": elapsed_ms},
            )
        except Exception:
            pass
        if ok:
            return
        if attempt < attempts:
            delay = min(float(backoff_max_s), float(backoff_s) * (2 ** max(0, attempt - 1)))
            if delay > 0:
                try:
                    sleep_fn(delay)
                except Exception:
                    pass
    raise RuntimeError(f"job {name} failed after {attempts} attempts: {last_error}")
