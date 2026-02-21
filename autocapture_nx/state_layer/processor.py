"""Idle-time state tape construction from derived SST state records."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.plugin_system.api import PluginContext

from .builder_jepa import JEPAStateBuilder
from .contracts import validate_state_edge, validate_state_span


@dataclass
class StateTapeStats:
    states_scanned: int = 0
    states_processed: int = 0
    spans_inserted: int = 0
    edges_inserted: int = 0
    evidence_inserted: int = 0
    batches: int = 0
    errors: int = 0
    workflow_runs: int = 0
    workflow_defs: int = 0
    anomaly_runs: int = 0
    alerts_emitted: int = 0
    training_runs: int = 0


def _normalize_counts(counts: Any) -> tuple[int, int, int]:
    if isinstance(counts, dict):
        return (
            int(counts.get("spans_inserted", 0) or 0),
            int(counts.get("edges_inserted", 0) or 0),
            int(counts.get("evidence_inserted", 0) or 0),
        )
    return (
        int(getattr(counts, "spans_inserted", 0) or 0),
        int(getattr(counts, "edges_inserted", 0) or 0),
        int(getattr(counts, "evidence_inserted", 0) or 0),
    )


class StateTapeProcessor:
    def __init__(self, system: Any) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._metadata = self._cap("storage.metadata")
        self._state_store = self._cap("storage.state_tape")
        self._vector_index = self._cap("state.vector_index")
        self._workflow_miner = self._cap("state.workflow_miner")
        self._anomaly = self._cap("state.anomaly")
        self._training = self._cap("state.training")
        self._logger = self._cap("observability.logger")
        self._events = self._cap("event.builder")
        # Builder construction may need the logger, so resolve it after logger is available.
        self._builder = self._resolve_builder()

    def _cap(self, name: str) -> Any | None:
        if hasattr(self._system, "has") and self._system.has(name):
            return self._system.get(name)
        if isinstance(self._system, dict):
            return self._system.get(name)
        return None

    def _state_cfg(self) -> dict[str, Any]:
        cfg = self._config.get("processing", {}).get("state_layer", {}) if isinstance(self._config, dict) else {}
        return cfg if isinstance(cfg, dict) else {}

    def _resolve_builder(self) -> Any:
        try:
            builder = self._cap("state.builder")
        except Exception:
            builder = None
        if builder is not None:
            return builder
        context = PluginContext(
            config=self._config if isinstance(self._config, dict) else {},
            get_capability=self._cap,
            logger=(self._logger.log if self._logger is not None and hasattr(self._logger, "log") else (lambda *_args, **_kwargs: None)),
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        plugin_id = str(self._state_cfg().get("builder_plugin_id") or "builtin.state.jepa_like")
        return JEPAStateBuilder(plugin_id, context)

    def _checkpoint_id(self, run_id: str, version_key: str | None = None) -> str:
        if version_key:
            return f"{run_id}/derived.state_tape.checkpoint/{version_key}"
        return f"{run_id}/derived.state_tape.checkpoint"

    def _load_checkpoint(self, run_id: str, version_key: str | None = None) -> dict[str, Any] | None:
        if self._metadata is None:
            return None
        record = self._metadata.get(self._checkpoint_id(run_id, version_key), None)
        if record is None and (version_key is None or version_key == "unknown"):
            record = self._metadata.get(self._checkpoint_id(run_id), None)
        if isinstance(record, dict) and record.get("record_type") == "derived.state_tape.checkpoint":
            return record
        return None

    def _store_checkpoint(
        self,
        run_id: str,
        last_record_id: str,
        processed_total: int,
        *,
        model_version: str | None = None,
        config_hash: str | None = None,
        version_key: str | None = None,
    ) -> None:
        if self._metadata is None:
            return
        ts_utc = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": 1,
            "record_type": "derived.state_tape.checkpoint",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "last_record_id": last_record_id,
            "processed_total": int(processed_total),
            "model_version": model_version or "",
            "config_hash": config_hash or "",
            "version_key": version_key or "",
        }
        payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
        if hasattr(self._metadata, "put_replace"):
            try:
                self._metadata.put_replace(self._checkpoint_id(run_id, version_key), payload)
            except Exception:
                self._metadata.put(self._checkpoint_id(run_id, version_key), payload)
        else:
            self._metadata.put(self._checkpoint_id(run_id, version_key), payload)

    def _builder_version_info(self) -> tuple[str | None, str | None, str]:
        model_version: str | None = None
        config_hash: str | None = None
        builder = self._builder
        if builder is None:
            return model_version, config_hash, "unknown"
        try:
            mv = getattr(builder, "model_version", None)
            if callable(mv):
                model_version = str(mv() or "")
            elif mv is not None:
                model_version = str(mv or "")
        except Exception:
            model_version = None
        if model_version is None:
            try:
                model_version = str(getattr(builder, "_model_version", "") or "")
            except Exception:
                model_version = None
        try:
            ch = getattr(builder, "config_hash", None)
            if callable(ch):
                config_hash = str(ch() or "")
            elif ch is not None:
                config_hash = str(ch or "")
        except Exception:
            config_hash = None
        if config_hash is None:
            try:
                config_hash = str(getattr(builder, "_config_hash", "") or "")
            except Exception:
                config_hash = None
        version_key = f"{model_version or 'unknown'}:{config_hash or 'unknown'}"
        return model_version, config_hash, version_key

    def _iter_state_records(self) -> list[tuple[str, str, dict[str, Any]]]:
        if self._metadata is None:
            return []
        records: list[tuple[str, str, dict[str, Any]]] = []
        for record_id in getattr(self._metadata, "keys", lambda: [])():
            record = self._metadata.get(record_id, {})
            if not isinstance(record, dict):
                continue
            if str(record.get("record_type")) != "derived.sst.state":
                continue
            run_id = str(record.get("run_id") or (record_id.split("/", 1)[0] if "/" in record_id else "run"))
            records.append((run_id, str(record_id), record))
        records.sort(key=lambda item: (item[0], _state_ts_ms(item[2]), item[1]))
        return records

    def process_step(
        self,
        *,
        should_abort: Any | None = None,
        budget_ms: int = 0,
    ) -> tuple[bool, StateTapeStats]:
        stats = StateTapeStats()
        state_cfg = self._state_cfg()
        if not bool(state_cfg.get("enabled", False)):
            return True, stats
        if self._metadata is None or self._state_store is None or self._builder is None:
            if self._logger is not None and hasattr(self._logger, "log"):
                self._logger.log("state_tape.missing_capabilities", {"metadata": bool(self._metadata), "state_store": bool(self._state_store), "builder": bool(self._builder)})
            return True, stats

        deadline = time.monotonic() + (budget_ms / 1000.0) if budget_ms and budget_ms > 0 else None

        def _expired() -> bool:
            if deadline is None:
                return False
            return time.monotonic() >= deadline

        records = self._iter_state_records()
        if not records:
            return True, stats

        max_states = int(state_cfg.get("batch", {}).get("max_states_per_run", 200) or 200)
        overlap = int(state_cfg.get("batch", {}).get("overlap_states", 1) or 1)
        processed_total = 0
        last_record_id: str | None = None

        by_run: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for run_id, record_id, record in records:
            by_run.setdefault(run_id, []).append((record_id, record))

        done = True
        model_version, config_hash, version_key = self._builder_version_info()
        for run_id, items in by_run.items():
            if should_abort and should_abort():
                done = False
                break
            if _expired():
                done = False
                break
            checkpoint = self._load_checkpoint(run_id, version_key)
            start_index = 0
            if checkpoint and checkpoint.get("last_record_id"):
                last_id = str(checkpoint.get("last_record_id"))
                for idx, (rid, _rec) in enumerate(items):
                    if rid == last_id:
                        start_index = idx + 1
                        break
            if start_index >= len(items):
                continue
            window = items[max(0, start_index - overlap) : min(len(items), start_index + max_states)]
            states = [rec for _rid, rec in window]
            if not states:
                continue
            stats.states_scanned += len(window)
            batch = {"session_id": run_id, "states": states}
            try:
                out = self._builder.process(batch)
            except Exception as exc:
                stats.errors += 1
                if self._logger is not None and hasattr(self._logger, "log"):
                    self._logger.log("state_tape.builder_error", {"error": str(exc)})
                continue
            spans = out.get("spans", []) if isinstance(out, dict) else []
            edges = out.get("edges", []) if isinstance(out, dict) else []
            spans = [s for s in spans if isinstance(s, dict)]
            edges = [e for e in edges if isinstance(e, dict)]
            for span in spans:
                validate_state_span(span)
            for edge in edges:
                validate_state_edge(edge)
            counts = self._state_store.insert_batch(spans, edges)
            spans_inserted, edges_inserted, evidence_inserted = _normalize_counts(counts)
            stats.spans_inserted += spans_inserted
            stats.edges_inserted += edges_inserted
            stats.evidence_inserted += evidence_inserted
            stats.batches += 1
            processed_total += len(window)
            stats.states_processed += len(window)
            vector_index = self._vector_index
            if vector_index is not None and hasattr(vector_index, "index_spans") and spans and bool(state_cfg.get("features", {}).get("index_enabled", True)):
                try:
                    vector_index.index_spans(spans)
                except Exception:
                    pass
            features = state_cfg.get("features", {}) if isinstance(state_cfg.get("features", {}), dict) else {}
            if bool(features.get("workflow_enabled", False)) and self._workflow_miner is not None and spans:
                try:
                    workflows = self._workflow_miner.mine({"session_id": run_id, "spans": spans, "edges": edges})
                    stats.workflow_runs += 1
                    stats.workflow_defs += len(workflows) if isinstance(workflows, list) else 0
                    append_audit_event(
                        action="state.workflow.mined",
                        actor="idle_processor",
                        outcome="ok",
                        details={"run_id": run_id, "workflows": stats.workflow_defs},
                    )
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None and hasattr(self._logger, "log"):
                        self._logger.log("state.workflow.error", {"error": str(exc)})
            if bool(features.get("anomaly_enabled", False)) and self._anomaly is not None and edges:
                try:
                    alerts = self._anomaly.detect(edges)
                    stats.anomaly_runs += 1
                    stats.alerts_emitted += len(alerts) if isinstance(alerts, list) else 0
                    append_audit_event(
                        action="state.anomaly.detected",
                        actor="idle_processor",
                        outcome="ok",
                        details={"run_id": run_id, "alerts": stats.alerts_emitted},
                    )
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None and hasattr(self._logger, "log"):
                        self._logger.log("state.anomaly.error", {"error": str(exc)})
            if bool(features.get("training_enabled", False)) and self._training is not None and spans:
                try:
                    _result = self._training.train({"session_id": run_id, "states": states, "spans": spans, "edges": edges})
                    stats.training_runs += 1
                    append_audit_event(
                        action="state.training.run",
                        actor="idle_processor",
                        outcome="ok",
                        details={"run_id": run_id},
                    )
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None and hasattr(self._logger, "log"):
                        self._logger.log("state.training.error", {"error": str(exc)})
            last_record_id = window[-1][0]
            self._store_checkpoint(
                run_id,
                last_record_id,
                processed_total,
                model_version=model_version,
                config_hash=config_hash,
                version_key=version_key,
            )
            append_audit_event(
                action="state_tape.append",
                actor="idle_processor",
                outcome="ok",
                details={
                    "run_id": run_id,
                    "states": len(window),
                    "spans_inserted": spans_inserted,
                    "edges_inserted": edges_inserted,
                },
            )
            if len(window) >= max_states:
                done = False
                break

        return done and not _expired(), stats


def _state_ts_ms(record: dict[str, Any]) -> int:
    screen_state_raw = record.get("screen_state")
    screen_state = screen_state_raw if isinstance(screen_state_raw, dict) else {}
    ts = screen_state.get("ts_ms")
    if ts is None:
        return 0
    try:
        return int(ts)
    except Exception:
        return 0
