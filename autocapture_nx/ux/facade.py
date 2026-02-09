"""NX UX facade shared by CLI and Web console."""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator, cast

from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.config import ConfigPaths, load_config, reset_user_config, restore_user_config, validate_config
from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    derivation_edge_id,
    extract_text_payload,
)
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.query import run_query
from autocapture_nx.kernel.telemetry import telemetry_snapshot, percentile
from autocapture_nx.kernel.atomic_write import atomic_write_json
from autocapture_nx.kernel.doctor import build_health_report
from autocapture_nx.kernel.logging import JsonlLogger
from autocapture_nx.plugin_system.manager import PluginManager
from autocapture_nx.processing.idle import _extract_frame, _get_media_blob


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


_MISSING = object()


def _deleted_marker() -> dict[str, Any]:
    return {"__deleted__": True}


def _is_deleted_marker(value: Any) -> bool:
    return isinstance(value, dict) and value.get("__deleted__") is True and len(value) == 1


def _snapshot_patch_values(current: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        if current is _MISSING:
            return _deleted_marker()
        return current
    snapshot: dict[str, Any] = {}
    for key, value in patch.items():
        if isinstance(value, dict):
            if isinstance(current, dict) and key in current:
                snapshot[key] = _snapshot_patch_values(current.get(key), value)
            else:
                snapshot[key] = _snapshot_patch_values(_MISSING, value)
        else:
            if isinstance(current, dict) and key in current:
                snapshot[key] = current.get(key)
            else:
                snapshot[key] = _deleted_marker()
    return snapshot


def _apply_revert_patch(target: Any, patch: Any) -> None:
    if not isinstance(target, dict) or not isinstance(patch, dict):
        return
    for key, value in patch.items():
        if _is_deleted_marker(value):
            if key in target:
                target.pop(key, None)
            continue
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, dict):
                target[key] = {}
            _apply_revert_patch(target[key], value)
            continue
        target[key] = value


def compute_slo_summary(
    config: dict[str, Any],
    telemetry: dict[str, Any],
    capture_status: dict[str, Any] | None,
    processing_state: dict[str, Any] | None,
) -> dict[str, Any]:
    perf_cfg = config.get("performance", {}) if isinstance(config, dict) else {}
    lag_threshold = float(perf_cfg.get("capture_lag_p95_ms", 1500))
    queue_threshold = float(perf_cfg.get("capture_queue_p95", 3))
    age_threshold = float(perf_cfg.get("capture_age_s", 10))
    query_threshold = float(perf_cfg.get("query_latency_ms", 2000))
    error_budget_pct = float(perf_cfg.get("error_budget_pct", 1.0))

    history = telemetry.get("history", {}) if isinstance(telemetry, dict) else {}
    capture_hist = history.get("capture", []) if isinstance(history, dict) else []
    query_hist = history.get("query", []) if isinstance(history, dict) else []
    lag_samples = [float(item.get("lag_ms", 0.0) or 0.0) for item in capture_hist if isinstance(item, dict)]
    queue_samples = [float(item.get("queue_depth", 0.0) or 0.0) for item in capture_hist if isinstance(item, dict)]
    query_samples = [float(item.get("latency_ms", 0.0) or 0.0) for item in query_hist if isinstance(item, dict)]
    lag_p95 = percentile(lag_samples, 95) if lag_samples else None
    queue_p95 = percentile(queue_samples, 95) if queue_samples else None
    query_p95 = percentile(query_samples, 95) if query_samples else None

    capture_age = None
    if isinstance(capture_status, dict):
        age_val = capture_status.get("last_capture_age_seconds")
        if isinstance(age_val, (int, float)):
            capture_age = float(age_val)

    capture_fail = False
    capture_unknown = False
    if lag_p95 is None or queue_p95 is None or capture_age is None:
        capture_unknown = True
    else:
        if lag_p95 > lag_threshold or queue_p95 > queue_threshold or capture_age > age_threshold:
            capture_fail = True

    query_fail = False
    query_unknown = False
    if query_p95 is None:
        query_unknown = True
    else:
        if query_p95 > query_threshold:
            query_fail = True

    total_samples = len(capture_hist)
    error_samples = 0
    if total_samples > 0:
        for item in capture_hist:
            if not isinstance(item, dict):
                continue
            lag_val = float(item.get("lag_ms", 0.0) or 0.0)
            queue_val = float(item.get("queue_depth", 0.0) or 0.0)
            if lag_val > lag_threshold or queue_val > queue_threshold:
                error_samples += 1
    error_budget_used_pct = (error_samples / total_samples * 100.0) if total_samples > 0 else None

    watchdog_state = None
    processing_fail = False
    if isinstance(processing_state, dict):
        watchdog = processing_state.get("watchdog") or {}
        if isinstance(watchdog, dict):
            watchdog_state = watchdog.get("state")
    if watchdog_state in {"stalled", "error"}:
        processing_fail = True

    capture_status_label = "unknown" if capture_unknown else ("fail" if capture_fail else "pass")
    processing_status_label = "fail" if processing_fail else "pass"
    query_status_label = "unknown" if query_unknown else ("fail" if query_fail else "pass")
    overall = "fail" if (capture_fail or processing_fail or query_fail) else ("unknown" if (capture_unknown or query_unknown) else "pass")

    return {
        "overall": overall,
        "error_budget_pct": error_budget_pct,
        "error_budget_used_pct": error_budget_used_pct,
        "window_samples": total_samples,
        "capture": {
            "lag_p95_ms": lag_p95,
            "lag_threshold_ms": lag_threshold,
            "queue_p95": queue_p95,
            "queue_threshold": queue_threshold,
            "age_s": capture_age,
            "age_threshold_s": age_threshold,
            "status": capture_status_label,
        },
        "processing": {
            "watchdog_state": watchdog_state,
            "status": processing_status_label,
        },
        "query": {
            "latency_p95_ms": query_p95,
            "latency_threshold_ms": query_threshold,
            "status": query_status_label,
        },
    }


class KernelManager:
    def __init__(
        self,
        paths: ConfigPaths,
        *,
        safe_mode: bool = False,
        persistent: bool = False,
        start_conductor: bool = False,
    ) -> None:
        self._paths = paths
        self._safe_mode = safe_mode
        self._persistent = persistent
        self._start_conductor = start_conductor
        self._lock = threading.Lock()
        self._kernel: Kernel | None = None
        self._system: Any | None = None
        self._last_error: str | None = None

    @contextmanager
    def session(self) -> Iterator[Any]:
        if not self._persistent:
            kernel = Kernel(self._paths, safe_mode=self._safe_mode)
            # One-shot sessions should be lightweight and avoid heavy boot-time fanout.
            system = kernel.boot(start_conductor=self._start_conductor, fast_boot=True)
            try:
                yield system
            finally:
                kernel.shutdown()
            return
        with self._lock:
            if self._kernel is None or self._system is None:
                self._kernel = Kernel(self._paths, safe_mode=self._safe_mode)
                try:
                    self._system = self._kernel.boot(start_conductor=self._start_conductor)
                    self._last_error = None
                except Exception as exc:
                    self._kernel = None
                    self._system = None
                    self._last_error = str(exc)
                    yield None
                    return
        try:
            yield self._system
        finally:
            return

    def kernel(self) -> Kernel | None:
        return self._kernel

    def last_error(self) -> str | None:
        return self._last_error

    def shutdown(self) -> None:
        with self._lock:
            if self._kernel is None:
                return
            self._kernel.shutdown()
            self._kernel = None
            self._system = None
            self._last_error = None


class UXFacade:
    def __init__(
        self,
        *,
        paths: ConfigPaths | None = None,
        safe_mode: bool = False,
        persistent: bool = False,
        start_conductor: bool = False,
        auto_start_capture: bool | None = None,
    ) -> None:
        self._paths = paths or default_config_paths()
        self._safe_mode = safe_mode
        self._persistent = persistent
        self._config = load_config(self._paths, safe_mode=safe_mode)
        self._kernel_mgr = KernelManager(
            self._paths,
            safe_mode=safe_mode,
            persistent=persistent,
            start_conductor=start_conductor,
        )
        self._run_active = False
        self._pause_lock = threading.Lock()
        self._pause_timer: threading.Timer | None = None
        self._paused_until_utc: str | None = None
        self._history_lock = threading.Lock()
        self._auto_start_capture(auto_start_capture)

    def _auto_start_capture(self, explicit: bool | None) -> None:
        if not self._persistent:
            return
        auto_start = (
            explicit
            if explicit is not None
            else bool(self._config.get("capture", {}).get("auto_start", False))
        )
        if not auto_start:
            return
        try:
            self.run_start()
        except Exception:
            return

    @property
    def config(self) -> dict[str, Any]:
        return dict(self._config)

    def reload_config(self) -> dict[str, Any]:
        self._config = load_config(self._paths, safe_mode=self._safe_mode)
        return dict(self._config)

    def doctor_report(self) -> dict[str, Any]:
        logger = None
        try:
            logger = JsonlLogger.from_config(self._config, name="core")
        except Exception:
            logger = None
        kernel = self._kernel_mgr.kernel()
        if kernel is None:
            kernel = Kernel(self._paths, safe_mode=self._safe_mode)
            kernel.boot(start_conductor=False)
            checks = kernel.doctor()
            try:
                system = kernel.system
                report = build_health_report(system=system, checks=checks) if system is not None else None
            except Exception:
                report = None
            kernel.shutdown()
        else:
            checks = kernel.doctor()
            try:
                system = kernel.system
                report = build_health_report(system=system, checks=checks) if system is not None else None
            except Exception:
                report = None
        if not isinstance(report, dict):
            ok = all(check.ok for check in checks)
            report = {
                "ok": ok,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "checks": [check.__dict__ for check in checks],
            }
        if logger is not None:
            try:
                report.setdefault("logs", {})["core_jsonl"] = logger.path
            except Exception:
                pass
        return report

    def diagnostics_bundle_create(self) -> dict[str, Any]:
        from autocapture_nx.kernel.diagnostics_bundle import create_diagnostics_bundle

        # Avoid heavy work: reuse doctor_report and export with redaction.
        report = self.doctor_report()
        result = create_diagnostics_bundle(config=self._config, doctor_report=report)
        return {"ok": True, "path": result.path, "sha256": result.bundle_sha256, "manifest": result.manifest}

    def resolve_citations(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            validator = system.get("citation.validator")
            return validator.resolve(citations)

    def verify_citations(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.resolve_citations(citations)
        return {"ok": bool(result.get("ok")), "errors": result.get("errors", [])}

    def config_get(self) -> dict[str, Any]:
        return dict(self._config)

    def _now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _history_path(self) -> Path:
        data_dir = Path(self._config.get("storage", {}).get("data_dir", "data"))
        return data_dir / "config_history.ndjson"

    def _bookmarks_path(self) -> Path:
        data_dir = Path(self._config.get("storage", {}).get("data_dir", "data"))
        return data_dir / "bookmarks.ndjson"

    def _append_ndjson(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, sort_keys=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _record_config_change(self, entry: dict[str, Any]) -> None:
        with self._history_lock:
            self._append_ndjson(self._history_path(), entry)

    def _load_history(self) -> list[dict[str, Any]]:
        path = self._history_path()
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries

    def config_history(self, limit: int = 20) -> dict[str, Any]:
        entries = self._load_history()
        if limit > 0:
            entries = entries[-limit:]
        return {"changes": entries}

    def config_revert(self, change_id: str) -> dict[str, Any]:
        if not change_id:
            raise ValueError("config_change_id_missing")
        history = self._load_history()
        target = None
        for entry in reversed(history):
            if entry.get("id") == change_id:
                target = entry
                break
        if target is None:
            raise KeyError("config_change_not_found")
        previous = target.get("previous")
        if not isinstance(previous, dict):
            raise ValueError("config_change_missing_previous")
        user_cfg = {}
        if self._paths.user_path.exists():
            user_cfg = json.loads(self._paths.user_path.read_text(encoding="utf-8"))
        prior_text = json.dumps(user_cfg, indent=2, sort_keys=True)
        _apply_revert_patch(user_cfg, previous)
        atomic_write_json(self._paths.user_path, user_cfg, sort_keys=True, indent=2)
        try:
            self.reload_config()
        except Exception as exc:
            atomic_write_json(self._paths.user_path, json.loads(prior_text), sort_keys=True, indent=2)
            self.reload_config()
            raise exc
        revert_entry = {
            "id": f"revert_{uuid.uuid4().hex}",
            "ts_utc": self._now_utc(),
            "scope": "config_revert",
            "source": "web",
            "target_id": str(change_id),
            "patch": previous,
        }
        self._record_config_change(revert_entry)
        return {"ok": True, "reverted": change_id}

    def _clear_pause_locked(self) -> None:
        if self._pause_timer is not None:
            try:
                self._pause_timer.cancel()
            except Exception:
                pass
            self._pause_timer = None
        self._paused_until_utc = None

    def config_set(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("config_patch_invalid")
        previous = _snapshot_patch_values(self._config, patch)
        user_cfg = {}
        if self._paths.user_path.exists():
            user_cfg = json.loads(self._paths.user_path.read_text(encoding="utf-8"))
        merged = _deep_merge(user_cfg, patch)
        validate_config(self._paths.schema_path, _deep_merge(self._config, patch))
        atomic_write_json(self._paths.user_path, merged, sort_keys=True, indent=2)
        updated = self.reload_config()
        entry = {
            "id": f"cfg_{uuid.uuid4().hex}",
            "ts_utc": self._now_utc(),
            "scope": "config",
            "source": "web",
            "patch": patch,
            "previous": previous,
        }
        self._record_config_change(entry)
        return updated

    def settings_schema(self) -> dict[str, Any]:
        from autocapture_nx.ux.settings_schema import build_settings_schema

        return build_settings_schema(self._paths.schema_path, self._paths.default_path, self._config)

    def config_reset(self) -> None:
        reset_user_config(self._paths)
        self.reload_config()

    def config_restore(self) -> None:
        restore_user_config(self._paths)
        self.reload_config()

    def plugins_list(self) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return {
            "plugins": [asdict(p) for p in manager.list_plugins()],
        }

    def plugins_timing(self) -> dict[str, Any]:
        def _percentile(values: list[int], pct: float) -> int | None:
            if not values:
                return None
            values = sorted(values)
            if len(values) == 1:
                return int(values[0])
            pct = max(0.0, min(100.0, float(pct)))
            rank = (pct / 100.0) * (len(values) - 1)
            low = int(rank)
            high = min(low + 1, len(values) - 1)
            frac = rank - low
            return int(round(values[low] + (values[high] - values[low]) * frac))

        with self._kernel_mgr.session() as system:
            trace = system.get("observability.plugin_trace") if system and hasattr(system, "get") else None
            if trace is None or not hasattr(trace, "snapshot"):
                return {"ok": True, "rows": [], "events": 0}
            events = trace.snapshot()
        by_key: dict[tuple[str, str, str], list[int]] = {}
        err_by_key: dict[tuple[str, str, str], int] = {}
        for ev in events if isinstance(events, list) else []:
            if not isinstance(ev, dict):
                continue
            pid = str(ev.get("plugin_id") or "")
            cap = str(ev.get("capability") or "")
            method = str(ev.get("method") or "")
            if not pid or not cap or not method:
                continue
            try:
                dur = int(ev.get("duration_ms") or 0)
            except Exception:
                dur = 0
            key = (pid, cap, method)
            by_key.setdefault(key, []).append(max(0, dur))
            if not bool(ev.get("ok", True)):
                err_by_key[key] = int(err_by_key.get(key, 0) or 0) + 1
        rows: list[dict[str, Any]] = []
        for (pid, cap, method), durs in sorted(by_key.items()):
            durs_sorted = sorted(durs)
            rows.append(
                {
                    "plugin_id": pid,
                    "capability": cap,
                    "method": method,
                    "calls": len(durs_sorted),
                    "errors": int(err_by_key.get((pid, cap, method), 0) or 0),
                    "total_ms": int(sum(durs_sorted)),
                    "p50_ms": _percentile(durs_sorted, 50.0),
                    "p95_ms": _percentile(durs_sorted, 95.0),
                    "max_ms": int(durs_sorted[-1]) if durs_sorted else None,
                }
            )
        return {"ok": True, "rows": rows, "events": int(len(events) if isinstance(events, list) else 0)}

    def plugins_settings_get(self, plugin_id: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        settings = manager.settings_get(plugin_id)
        schema = manager.settings_schema_for(plugin_id)
        return {"plugin_id": plugin_id, "settings": settings, "schema": schema}

    def plugins_settings_set(self, plugin_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        previous_leaf = _snapshot_patch_values(
            self._config.get("plugins", {}).get("settings", {}).get(plugin_id, _MISSING),
            patch,
        )
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        manager.settings_set(plugin_id, patch)
        self.reload_config()
        entry = {
            "id": f"plugin_{uuid.uuid4().hex}",
            "ts_utc": self._now_utc(),
            "scope": "plugin_settings",
            "source": "web",
            "plugin_id": plugin_id,
            "patch": {"plugins": {"settings": {plugin_id: patch}}},
            "previous": {"plugins": {"settings": {plugin_id: previous_leaf}}},
        }
        self._record_config_change(entry)
        return manager.settings_get(plugin_id)

    def plugins_enable(self, plugin_id: str) -> None:
        previous_leaf = _snapshot_patch_values(
            self._config.get("plugins", {}).get("enabled", {}).get(plugin_id, _MISSING),
            True,
        )
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        manager.enable(plugin_id)
        self.reload_config()
        entry = {
            "id": f"plugin_enable_{uuid.uuid4().hex}",
            "ts_utc": self._now_utc(),
            "scope": "plugin_enable",
            "source": "web",
            "plugin_id": plugin_id,
            "patch": {"plugins": {"enabled": {plugin_id: True}}},
            "previous": {"plugins": {"enabled": {plugin_id: previous_leaf}}},
        }
        self._record_config_change(entry)

    def plugins_disable(self, plugin_id: str) -> None:
        previous_leaf = _snapshot_patch_values(
            self._config.get("plugins", {}).get("enabled", {}).get(plugin_id, _MISSING),
            False,
        )
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        manager.disable(plugin_id)
        self.reload_config()
        entry = {
            "id": f"plugin_disable_{uuid.uuid4().hex}",
            "ts_utc": self._now_utc(),
            "scope": "plugin_disable",
            "source": "web",
            "plugin_id": plugin_id,
            "patch": {"plugins": {"enabled": {plugin_id: False}}},
            "previous": {"plugins": {"enabled": {plugin_id: previous_leaf}}},
        }
        self._record_config_change(entry)

    def plugins_approve(self) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return manager.approve_hashes()

    def plugins_reload(self, plugin_ids: list[str] | None = None) -> dict[str, Any]:
        kernel = self._kernel_mgr.kernel()
        if kernel is None:
            raise RuntimeError("kernel_not_running")
        return kernel.reload_plugins(plugin_ids=plugin_ids)

    def query(self, text: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            return run_query(system, text)

    def state_query(self, text: str) -> dict[str, Any]:
        from autocapture_nx.kernel.query import run_state_query

        with self._kernel_mgr.session() as system:
            return run_state_query(system, text)

    def state_jepa_approve(self, model_version: str, training_run_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("state.training"):
                raise RuntimeError("state_training_unavailable")
            trainer = system.get("state.training")
            if not hasattr(trainer, "approve_model"):
                raise RuntimeError("state_training_missing_approve")
            return trainer.approve_model(model_version, training_run_id)

    def state_jepa_list(self, include_archived: bool = True) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("state.training"):
                raise RuntimeError("state_training_unavailable")
            trainer = system.get("state.training")
            if not hasattr(trainer, "list_models"):
                raise RuntimeError("state_training_missing_list")
            return {"models": trainer.list_models(include_archived=include_archived)}

    def state_jepa_approve_latest(self, include_archived: bool = False) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("state.training"):
                raise RuntimeError("state_training_unavailable")
            trainer = system.get("state.training")
            if not hasattr(trainer, "approve_latest"):
                raise RuntimeError("state_training_missing_approve_latest")
            return trainer.approve_latest(include_archived=include_archived)

    def state_jepa_promote(self, model_version: str, training_run_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("state.training"):
                raise RuntimeError("state_training_unavailable")
            trainer = system.get("state.training")
            if not hasattr(trainer, "promote_model"):
                raise RuntimeError("state_training_missing_promote")
            return trainer.promote_model(model_version, training_run_id)

    def state_jepa_report(self, model_version: str, training_run_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("state.training"):
                raise RuntimeError("state_training_unavailable")
            trainer = system.get("state.training")
            if not hasattr(trainer, "report"):
                raise RuntimeError("state_training_missing_report")
            return trainer.report(model_version, training_run_id)

    def state_jepa_archive(self, dry_run: bool = False) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("state.training"):
                raise RuntimeError("state_training_unavailable")
            trainer = system.get("state.training")
            if not hasattr(trainer, "archive_models"):
                raise RuntimeError("state_training_missing_archive")
            return trainer.archive_models(dry_run=dry_run)

    def devtools_diffusion(self, axis: str, k_variants: int = 1, dry_run: bool | None = None) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            harness = system.get("devtools.diffusion")
            return harness.run(axis=axis, k_variants=k_variants, dry_run=dry_run)

    def devtools_ast_ir(self, scan_root: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            tool = system.get("devtools.ast_ir")
            return tool.run(scan_root=scan_root)

    def enrich(self, force: bool = True) -> dict[str, Any]:
        from autocapture.runtime.conductor import create_conductor

        with self._kernel_mgr.session() as system:
            conductor = create_conductor(system)
            return conductor.run_once(force=force)

    def keys_rotate(self) -> dict[str, Any]:
        from autocapture_nx.kernel.key_rotation import rotate_keys

        with self._kernel_mgr.session() as system:
            return rotate_keys(system)

    def status(self) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            kernel_error = self._kernel_mgr.last_error()
            kernel = self._kernel_mgr.kernel()
            safe_mode = bool(getattr(kernel, "safe_mode", self._safe_mode)) if kernel is not None else bool(self._safe_mode)
            safe_mode_reason = getattr(kernel, "safe_mode_reason", None) if kernel is not None else None
            crash_loop = None
            if kernel is not None and hasattr(kernel, "crash_loop_status"):
                try:
                    crash_loop = kernel.crash_loop_status()
                except Exception:
                    crash_loop = None
            builder = system.get("event.builder") if system and hasattr(system, "get") else None
            run_id = builder.run_id if builder is not None else ""
            ledger_head = builder.ledger_head() if builder is not None else None
            capture_status = self._capture_status_payload()
            processing_state = self._processing_state_payload(system)
            telemetry = telemetry_snapshot()
            slo = compute_slo_summary(self._config, telemetry, capture_status, processing_state)
            return {
                "run_id": run_id,
                "ledger_head": ledger_head,
                "plugins_loaded": len(getattr(system, "plugins", []) or []),
                "safe_mode": safe_mode,
                "safe_mode_reason": safe_mode_reason,
                "crash_loop": crash_loop,
                "capture_active": bool(self._run_active),
                "paused_until_utc": self._paused_until_utc,
                "paused": bool(self._paused_until_utc),
                "capture_controls_enabled": self._capture_controls_enabled(),
                "capture_status": capture_status,
                "processing_state": processing_state,
                "slo": slo,
                "kernel_ready": system is not None,
                "kernel_error": kernel_error,
            }

    def _capture_status_payload(self) -> dict[str, Any]:
        from autocapture.storage.pressure import sample_disk_pressure

        telemetry = telemetry_snapshot()
        latest = telemetry.get("latest", {}) if isinstance(telemetry, dict) else {}
        capture_payload = latest.get("capture") if isinstance(latest, dict) else None
        screenshot_payload = latest.get("capture.screenshot") if isinstance(latest, dict) else None
        output_payload = latest.get("capture.output") if isinstance(latest, dict) else None

        def _parse_ts(payload: dict[str, Any] | None) -> datetime | None:
            if not isinstance(payload, dict):
                return None
            ts = payload.get("ts_utc")
            if not ts:
                return None
            value = str(ts)
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

        candidates = [screenshot_payload, output_payload, capture_payload]
        latest_ts = None
        for payload in candidates:
            ts = _parse_ts(payload)
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts
        last_capture_age = None
        last_capture_ts = latest_ts.isoformat() if latest_ts else None
        if latest_ts is not None:
            last_capture_age = max(0.0, (datetime.now(timezone.utc) - latest_ts).total_seconds())

        disk = None
        try:
            sample = sample_disk_pressure(self._config)
            disk_cfg = self._config.get("storage", {}).get("disk_pressure", {}) if isinstance(self._config, dict) else {}
            hard_mb = int(disk_cfg.get("watermark_hard_mb", 0) or 0)
            hard_halt = bool(getattr(sample, "hard_halt", False))
            if not hard_halt and hard_mb > 0:
                hard_halt = sample.free_bytes <= (hard_mb * 1024 * 1024)
            disk = {
                "level": sample.level,
                "free_gb": sample.free_gb,
                "free_bytes": sample.free_bytes,
                "hard_halt": hard_halt,
            }
        except Exception:
            disk = None

        payload = {
            "last_capture_ts_utc": last_capture_ts,
            "last_capture_age_seconds": last_capture_age,
            "queue_depth": capture_payload.get("queue_depth") if isinstance(capture_payload, dict) else None,
            "drops_total": capture_payload.get("drops_total") if isinstance(capture_payload, dict) else None,
            "lag_ms": capture_payload.get("lag_ms") if isinstance(capture_payload, dict) else None,
            "disk": disk,
        }
        return payload

    def _processing_state_payload(self, system: Any | None = None) -> dict[str, Any]:
        stats = None
        watchdog = None
        if system is not None and hasattr(system, "get"):
            scheduler = system.get("runtime.scheduler") if system and hasattr(system, "get") else None
            stats = scheduler.last_stats() if scheduler is not None and hasattr(scheduler, "last_stats") else None
            conductor = system.get("runtime.conductor") if system and hasattr(system, "get") else None
            if conductor is not None and hasattr(conductor, "watchdog_state"):
                try:
                    watchdog = conductor.watchdog_state()
                except Exception:
                    watchdog = None
        if stats is None:
            stats = self.scheduler_status().get("stats")
        if stats is not None and hasattr(stats, "__dataclass_fields__"):
            stats = asdict(cast(Any, stats))
        if not isinstance(stats, dict):
            return {"mode": None, "paused": None, "reason": None, "watchdog": watchdog}
        mode = stats.get("mode")
        reason = stats.get("reason")
        paused = bool(mode == "ACTIVE_CAPTURE_ONLY")
        if watchdog is None:
            telemetry = telemetry_snapshot()
            latest = telemetry.get("latest", {}) if isinstance(telemetry, dict) else {}
            watchdog = latest.get("processing.watchdog") if isinstance(latest, dict) else None
        return {"mode": mode, "paused": paused, "reason": reason, "watchdog": watchdog}

    def _capture_controls_enabled(self) -> bool:
        runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
        controls_cfg = runtime_cfg.get("capture_controls", {}) if isinstance(runtime_cfg, dict) else {}
        return bool(controls_cfg.get("enabled", False))

    def _start_components(self) -> None:
        started = False
        with self._kernel_mgr.session() as system:
            capture = system.get("capture.source") if system and hasattr(system, "get") else None
            screenshot = (
                system.get("capture.screenshot")
                if system and hasattr(system, "has") and system.has("capture.screenshot")
                else None
            )
            audio = system.get("capture.audio") if system and hasattr(system, "get") else None
            input_tracker = system.get("tracking.input") if system and hasattr(system, "get") else None
            window_meta = system.get("window.metadata") if system and hasattr(system, "get") else None
            cursor_tracker = (
                system.get("tracking.cursor")
                if system and hasattr(system, "has") and system.has("tracking.cursor")
                else None
            )
            clipboard = (
                system.get("tracking.clipboard")
                if system and hasattr(system, "has") and system.has("tracking.clipboard")
                else None
            )
            file_activity = (
                system.get("tracking.file_activity")
                if system and hasattr(system, "has") and system.has("tracking.file_activity")
                else None
            )
            for component in (
                capture,
                screenshot,
                audio,
                input_tracker,
                window_meta,
                cursor_tracker,
                clipboard,
                file_activity,
            ):
                if component is None:
                    continue
                if hasattr(component, "start"):
                    try:
                        component.start()
                        started = True
                    except Exception:
                        continue
        self._run_active = started

    def _stop_components(self) -> None:
        with self._kernel_mgr.session() as system:
            capture = system.get("capture.source") if system and hasattr(system, "get") else None
            screenshot = (
                system.get("capture.screenshot")
                if system and hasattr(system, "has") and system.has("capture.screenshot")
                else None
            )
            audio = system.get("capture.audio") if system and hasattr(system, "get") else None
            input_tracker = system.get("tracking.input") if system and hasattr(system, "get") else None
            window_meta = system.get("window.metadata") if system and hasattr(system, "get") else None
            cursor_tracker = (
                system.get("tracking.cursor")
                if system and hasattr(system, "has") and system.has("tracking.cursor")
                else None
            )
            clipboard = (
                system.get("tracking.clipboard")
                if system and hasattr(system, "has") and system.has("tracking.clipboard")
                else None
            )
            file_activity = (
                system.get("tracking.file_activity")
                if system and hasattr(system, "has") and system.has("tracking.file_activity")
                else None
            )
            for component in (capture, screenshot, audio, input_tracker, window_meta, cursor_tracker, clipboard, file_activity):
                if component is None:
                    continue
                if hasattr(component, "stop"):
                    component.stop()
        self._run_active = False

    def run_start(self) -> dict[str, Any]:
        with self._pause_lock:
            self._clear_pause_locked()
        # Fail closed: require explicit capture consent if configured.
        try:
            privacy_cfg = self._config.get("privacy", {}) if isinstance(self._config, dict) else {}
            capture_cfg = privacy_cfg.get("capture", {}) if isinstance(privacy_cfg, dict) else {}
            require_consent = bool(capture_cfg.get("require_consent", True))
            if require_consent:
                from autocapture_nx.kernel.consent import load_capture_consent

                data_dir = str(self._config.get("storage", {}).get("data_dir", "data"))
                consent = load_capture_consent(data_dir=data_dir)
                if not consent.accepted:
                    return {"ok": False, "error": "consent_required", "running": False}
        except Exception:
            return {"ok": False, "error": "consent_check_failed", "running": False}

        self._start_components()
        # Ledger an operator capture start event (append-only).
        with self._kernel_mgr.session() as system:
            builder = system.get("event.builder") if system and hasattr(system, "get") else None
            if builder is not None and hasattr(builder, "ledger_entry"):
                try:
                    builder.ledger_entry(
                        "operator.capture.start",
                        inputs=[],
                        outputs=[],
                        payload={"event": "capture.start"},
                    )
                except Exception:
                    pass
        return {"ok": True, "running": True}

    def run_stop(self, *, preserve_pause: bool = False) -> dict[str, Any]:
        if not self._capture_controls_enabled():
            return {"ok": False, "error": "capture_controls_disabled"}
        if not preserve_pause:
            with self._pause_lock:
                self._clear_pause_locked()
        self._stop_components()
        with self._kernel_mgr.session() as system:
            builder = system.get("event.builder") if system and hasattr(system, "get") else None
            if builder is not None and hasattr(builder, "ledger_entry"):
                try:
                    builder.ledger_entry(
                        "operator.capture.stop",
                        inputs=[],
                        outputs=[],
                        payload={"event": "capture.stop"},
                    )
                except Exception:
                    pass
        return {"ok": True, "running": False}

    def run_pause(self, minutes: float) -> dict[str, Any]:
        if not self._capture_controls_enabled():
            return {"ok": False, "error": "capture_controls_disabled"}
        delay_s = max(0.0, float(minutes) * 60.0)
        self._stop_components()
        paused_until = None
        with self._pause_lock:
            self._clear_pause_locked()
            if delay_s > 0:
                paused_until = datetime.now(timezone.utc) + timedelta(seconds=delay_s)
                self._paused_until_utc = paused_until.isoformat()

                def _resume() -> None:
                    with self._pause_lock:
                        self._paused_until_utc = None
                        self._pause_timer = None
                    self._start_components()

                timer = threading.Timer(delay_s, _resume)
                timer.daemon = True
                self._pause_timer = timer
                timer.start()
        return {"ok": True, "paused_until_utc": self._paused_until_utc}

    def scheduler_status(self) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            scheduler = system.get("runtime.scheduler") if system and hasattr(system, "get") else None
            stats = scheduler.last_stats() if scheduler is not None and hasattr(scheduler, "last_stats") else None
            if stats is None:
                return {"stats": None}
            try:
                stats_payload: Any = asdict(stats)
            except TypeError:
                stats_payload = stats
            return {"stats": stats_payload}

    def keyring_status(self) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not hasattr(system, "has") or not system.has("storage.keyring"):
                return {"ok": False, "error": "keyring_missing"}
            keyring = system.get("storage.keyring")
            if hasattr(keyring, "status"):
                return {"ok": True, "status": asdict(keyring.status())}
            return {"ok": True, "status": {"active_key_ids": {}, "keyring_path": ""}}

    def verify_ledger(self, path: str | None = None) -> dict[str, Any]:
        from autocapture.pillars.citable import verify_ledger

        if path:
            ledger_path = Path(path)
        else:
            data_dir = Path(self._config.get("storage", {}).get("data_dir", "data"))
            ledger_path = data_dir / "ledger.ndjson"
        if not ledger_path.exists():
            return {"ok": True, "missing": True, "path": str(ledger_path)}
        ok, errors = verify_ledger(ledger_path)
        return {"ok": ok, "errors": errors, "path": str(ledger_path)}

    def verify_anchors(self, path: str | None = None) -> dict[str, Any]:
        from autocapture.pillars.citable import verify_anchors

        with self._kernel_mgr.session() as system:
            config = system.config if hasattr(system, "config") else {}
            anchor_cfg = config.get("storage", {}).get("anchor", {})
            anchor_path = Path(path) if path else Path(anchor_cfg.get("path", "data_anchor/anchors.ndjson"))
            keyring = system.get("storage.keyring") if system and hasattr(system, "has") and system.has("storage.keyring") else None
            ok, errors = verify_anchors(anchor_path, keyring)
            return {"ok": ok, "errors": errors, "path": str(anchor_path)}

    def verify_evidence(self) -> dict[str, Any]:
        from autocapture.pillars.citable import verify_evidence

        with self._kernel_mgr.session() as system:
            metadata = system.get("storage.metadata") if system is not None else None
            media = system.get("storage.media") if system is not None else None
            ok, errors = verify_evidence(metadata, media)
            return {"ok": ok, "errors": errors}

    def integrity_scan(self) -> dict[str, Any]:
        from autocapture.pillars.citable import integrity_scan

        with self._kernel_mgr.session() as system:
            config = system.config if hasattr(system, "config") else {}
            storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
            data_dir = Path(storage_cfg.get("data_dir", "data"))
            ledger_path = data_dir / "ledger.ndjson"
            anchor_path = Path(storage_cfg.get("anchor", {}).get("path", "data_anchor/anchors.ndjson"))
            keyring = system.get("storage.keyring") if system is not None and hasattr(system, "has") and system.has("storage.keyring") else None
            return integrity_scan(
                ledger_path=ledger_path,
                anchor_path=anchor_path,
                metadata=system.get("storage.metadata") if system is not None else None,
                media=system.get("storage.media") if system is not None else None,
                keyring=keyring,
            )

    def citations_resolve(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            validator = system.get("citation.validator")
            return validator.resolve(citations)

    def citations_verify(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.citations_resolve(citations)
        return {"ok": bool(result.get("ok")), "errors": result.get("errors", [])}

    def export_proof_bundle(
        self,
        evidence_ids: list[str],
        output_path: str,
        *,
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from autocapture_nx.kernel.proof_bundle import export_proof_bundle

        with self._kernel_mgr.session() as system:
            config = system.config if hasattr(system, "config") else {}
            storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
            data_dir = storage_cfg.get("data_dir", "data")
            ledger_path = Path(data_dir) / "ledger.ndjson"
            anchor_path = Path(storage_cfg.get("anchor", {}).get("path", "data_anchor/anchors.ndjson"))
            report = export_proof_bundle(
                metadata=system.get("storage.metadata"),
                media=system.get("storage.media"),
                keyring=system.get("storage.keyring") if system.has("storage.keyring") else None,
                ledger_path=ledger_path,
                anchor_path=anchor_path,
                output_path=output_path,
                evidence_ids=evidence_ids,
                citations=citations,
            )
            return asdict(report)

    def replay_proof_bundle(self, bundle_path: str) -> dict[str, Any]:
        from autocapture_nx.kernel.replay import replay_bundle

        return asdict(replay_bundle(bundle_path))

    def storage_compact(self, *, dry_run: bool = False) -> dict[str, Any]:
        from autocapture.storage.compaction import compact_derived

        with self._kernel_mgr.session() as system:
            result = compact_derived(
                system.get("storage.metadata"),
                system.get("storage.media"),
                system.config,
                dry_run=dry_run,
                event_builder=system.get("event.builder"),
            )
            return asdict(result)

    def storage_forecast(self, data_dir: str | None = None) -> dict[str, Any]:
        from autocapture.storage.forecast import forecast_from_journal

        target = data_dir or self._config.get("storage", {}).get("data_dir", "data")
        result = forecast_from_journal(str(target))
        return asdict(result)

    def metadata_latest(self, record_type: str | None = None, limit: int = 25) -> dict[str, Any]:
        limit_val = max(1, min(int(limit or 0), 200))
        with self._kernel_mgr.session() as system:
            metadata = system.get("storage.metadata")
            if metadata is None:
                return {"records": [], "error": "metadata_unavailable"}
            if hasattr(metadata, "latest"):
                records = metadata.latest(record_type=record_type, limit=limit_val)
                return {"records": records}
            return {"records": [], "error": "metadata_backend_not_queryable"}

    def metadata_get(self, record_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            metadata = system.get("storage.metadata")
            if metadata is None:
                return {"record_id": record_id, "record": None, "error": "metadata_unavailable"}
            return {"record_id": record_id, "record": metadata.get(record_id, None)}

    def _media_payload(self, media: Any, record_id: str, record: dict[str, Any] | None) -> dict[str, Any]:
        if media is None or not hasattr(media, "get"):
            return {"record_id": record_id, "error": "media_unavailable", "status": 503}
        try:
            data = media.get(record_id, None)
        except Exception as exc:
            return {
                "record_id": record_id,
                "error": "media_get_failed",
                "detail": str(exc),
                "status": 500,
            }
        if data is None:
            return {"record_id": record_id, "error": "media_not_found", "status": 404}
        content_type = "application/octet-stream"
        if isinstance(record, dict):
            content_type = record.get("content_type") or content_type
        return {"record_id": record_id, "content_type": content_type, "data": data}

    def media_latest(self, record_type: str | None = None) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None:
                return {
                    "error": "kernel_unavailable",
                    "detail": self._kernel_mgr.last_error(),
                    "status": 503,
                }
            metadata = system.get("storage.metadata")
            media = system.get("storage.media")
            if metadata is None:
                return {"error": "metadata_unavailable", "status": 503}
            def _parse_ts(value: Any) -> datetime | None:
                if not value:
                    return None
                text = str(value)
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                try:
                    return datetime.fromisoformat(text)
                except ValueError:
                    return None

            def _record_ts(record: dict[str, Any]) -> datetime | None:
                for key in ("ts_utc", "ts_end_utc", "ts_start_utc"):
                    ts_val = _parse_ts(record.get(key))
                    if ts_val is not None:
                        return ts_val
                return None

            records = None
            if hasattr(metadata, "latest"):
                records = metadata.latest(record_type=record_type, limit=1)
            elif hasattr(metadata, "keys") and hasattr(metadata, "get"):
                latest_entry: tuple[str, dict[str, Any]] | None = None
                latest_ts: datetime | None = None
                for key in metadata.keys():
                    record = metadata.get(key, None)
                    if not isinstance(record, dict):
                        continue
                    if record_type and str(record.get("record_type", "")) != str(record_type):
                        continue
                    ts_val = _record_ts(record)
                    if latest_entry is None:
                        latest_entry = (str(key), record)
                        latest_ts = ts_val
                        continue
                    if ts_val is None:
                        continue
                    if latest_ts is None or ts_val > latest_ts:
                        latest_entry = (str(key), record)
                        latest_ts = ts_val
                if latest_entry is not None:
                    latest_record_id, latest_record = latest_entry
                    records = [{"record_id": latest_record_id, "record": latest_record}]
            if records is None:
                return {"error": "metadata_backend_not_queryable", "status": 501}
            if not records:
                return {"error": "no_records", "status": 404}
            entry = records[0] if isinstance(records, list) else None
            record = entry.get("record") if isinstance(entry, dict) else None
            record_id: str | None = None
            if isinstance(entry, dict):
                record_id = entry.get("record_id") or entry.get("id")
            if not record_id and isinstance(record, dict):
                record_id = record.get("record_id") or record.get("id")
            if not record_id:
                return {"error": "record_id_missing", "status": 500}
            if record is None or not isinstance(record, dict):
                record = metadata.get(record_id, None) if hasattr(metadata, "get") else None
            return self._media_payload(media, str(record_id), record if isinstance(record, dict) else None)

    def media_get(self, record_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None:
                return {
                    "record_id": record_id,
                    "error": "kernel_unavailable",
                    "detail": self._kernel_mgr.last_error(),
                    "status": 503,
                }
            metadata = system.get("storage.metadata")
            media = system.get("storage.media")
            record = metadata.get(record_id, None) if metadata is not None and hasattr(metadata, "get") else None
            return self._media_payload(media, record_id, record if isinstance(record, dict) else None)

    def _trace_stale_map(self, system: Any) -> dict[str, str]:
        try:
            stale_cap = system.get("integrity.stale") if system is not None else None
        except Exception:
            stale_cap = None
        if stale_cap is not None and hasattr(stale_cap, "target"):
            stale_cap = getattr(stale_cap, "target")
        if isinstance(stale_cap, dict):
            return dict(stale_cap)
        return {}

    def _trace_entry_mentions(self, entry: Any, record_id: str) -> bool:
        if not isinstance(entry, dict):
            return False
        if entry.get("record_id") == record_id:
            return True
        inputs = entry.get("inputs")
        if isinstance(inputs, list) and record_id in inputs:
            return True
        outputs = entry.get("outputs")
        if isinstance(outputs, list) and record_id in outputs:
            return True
        payload = entry.get("payload")
        if isinstance(payload, dict):
            if payload.get("record_id") == record_id:
                return True
            if payload.get("parent_evidence_id") == record_id:
                return True
            if payload.get("source_id") == record_id:
                return True
            if payload.get("derived_id") == record_id:
                return True
            if payload.get("frame_id") == record_id:
                return True
            payload_inputs = payload.get("inputs")
            if isinstance(payload_inputs, list) and record_id in payload_inputs:
                return True
            payload_outputs = payload.get("outputs")
            if isinstance(payload_outputs, list) and record_id in payload_outputs:
                return True
        return False

    def _trace_scan_ndjson(self, path: Path, record_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        hits: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if self._trace_entry_mentions(entry, record_id):
                hits.append(entry)
        if limit > 0:
            hits = hits[-limit:]
        return hits

    def _trace_record_refers(self, record: Any, record_id: str) -> bool:
        if not isinstance(record, dict):
            return False
        if record.get("parent_evidence_id") == record_id:
            return True
        if record.get("source_id") == record_id:
            return True
        if record.get("parent_id") == record_id or record.get("child_id") == record_id:
            return True
        if record.get("frame_id") == record_id:
            return True
        provenance = record.get("provenance")
        if isinstance(provenance, dict):
            frame_ids = provenance.get("frame_ids")
            if isinstance(frame_ids, (list, tuple)) and record_id in frame_ids:
                return True
        return False

    def _trace_find_derived(self, metadata: Any, record_id: str, run_id: str | None) -> list[dict[str, Any]]:
        if metadata is None or not hasattr(metadata, "keys"):
            return []
        derived: list[dict[str, Any]] = []
        seen: set[str] = set()
        prefix = f"{run_id}/" if run_id else None
        for key in getattr(metadata, "keys", lambda: [])():
            if prefix and not str(key).startswith(prefix):
                continue
            if key in seen:
                continue
            record = metadata.get(key, None)
            if not isinstance(record, dict):
                continue
            record_type = str(record.get("record_type", ""))
            if not record_type.startswith("derived."):
                continue
            if not self._trace_record_refers(record, record_id):
                continue
            derived.append({"record_id": str(key), "record": record})
            seen.add(str(key))
        return derived

    def trace_latest(self, record_type: str | None = None) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None:
                return {
                    "error": "kernel_unavailable",
                    "detail": self._kernel_mgr.last_error(),
                    "status": 503,
                }
            metadata = system.get("storage.metadata")
            if metadata is None:
                return {"error": "metadata_unavailable", "status": 503}
            def _parse_ts(value: Any) -> datetime | None:
                if not value:
                    return None
                text = str(value)
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                try:
                    return datetime.fromisoformat(text)
                except ValueError:
                    return None

            def _record_ts(record: dict[str, Any]) -> datetime | None:
                for key in ("ts_utc", "ts_end_utc", "ts_start_utc"):
                    ts_val = _parse_ts(record.get(key))
                    if ts_val is not None:
                        return ts_val
                return None

            records = None
            if hasattr(metadata, "latest"):
                records = metadata.latest(record_type=record_type, limit=1)
            elif hasattr(metadata, "keys") and hasattr(metadata, "get"):
                latest_entry: tuple[str, dict[str, Any]] | None = None
                latest_ts: datetime | None = None
                for key in metadata.keys():
                    record = metadata.get(key, None)
                    if not isinstance(record, dict):
                        continue
                    if record_type and str(record.get("record_type", "")) != str(record_type):
                        continue
                    ts_val = _record_ts(record)
                    if latest_entry is None:
                        latest_entry = (str(key), record)
                        latest_ts = ts_val
                        continue
                    if ts_val is None:
                        continue
                    if latest_ts is None or ts_val > latest_ts:
                        latest_entry = (str(key), record)
                        latest_ts = ts_val
                if latest_entry is not None:
                    latest_record_id, latest_record = latest_entry
                    records = [{"record_id": latest_record_id, "record": latest_record}]
            if records is None:
                return {"error": "metadata_backend_not_queryable", "status": 501}
            if not records:
                return {"error": "no_records", "status": 404}
            entry = records[0] if isinstance(records, list) else None
            record = entry.get("record") if isinstance(entry, dict) else None
            record_id: str | None = None
            if isinstance(entry, dict):
                record_id = entry.get("record_id") or entry.get("id")
            if not record_id and isinstance(record, dict):
                record_id = record.get("record_id") or record.get("id")
            if not record_id:
                return {"error": "record_id_missing", "status": 500}
            if record is None or not isinstance(record, dict):
                record = metadata.get(record_id, None) if hasattr(metadata, "get") else None
            stale_map = self._trace_stale_map(system)
            stale_reason = stale_map.get(str(record_id))
            return {
                "record_id": str(record_id),
                "record": record,
                "stale": bool(stale_reason),
                "stale_reason": stale_reason,
            }

    def trace_record(self, record_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None:
                return {
                    "record_id": record_id,
                    "error": "kernel_unavailable",
                    "detail": self._kernel_mgr.last_error(),
                    "status": 503,
                }
            metadata = system.get("storage.metadata")
            if metadata is None:
                return {"record_id": record_id, "record": None, "error": "metadata_unavailable", "status": 503}
            record = metadata.get(record_id, None) if hasattr(metadata, "get") else None
            if record is None:
                return {"record_id": record_id, "record": None, "error": "record_not_found", "status": 404}
            run_id = record.get("run_id") if isinstance(record, dict) else None
            derived = self._trace_find_derived(metadata, record_id, str(run_id) if run_id else None)
            data_dir = Path(self._config.get("storage", {}).get("data_dir", "data"))
            journal_path = data_dir / "journal.ndjson"
            ledger_path = data_dir / "ledger.ndjson"
            journal_hits = self._trace_scan_ndjson(journal_path, record_id, limit=200)
            ledger_hits = self._trace_scan_ndjson(ledger_path, record_id, limit=200)
            stale_map = self._trace_stale_map(system)
            stale_reason = stale_map.get(record_id)
            return {
                "record_id": record_id,
                "record": record,
                "record_type": record.get("record_type") if isinstance(record, dict) else None,
                "derived": derived,
                "derived_count": len(derived),
                "journal": journal_hits,
                "ledger": ledger_hits,
                "stale": bool(stale_reason),
                "stale_reason": stale_reason,
            }

    def trace_preview(self, record_id: str) -> dict[str, Any]:
        def _guess_content_type(blob: bytes, fallback: str | None = None) -> str:
            if blob.startswith(b"\x89PNG\r\n\x1a\n"):
                return "image/png"
            if blob.startswith(b"\xff\xd8\xff"):
                return "image/jpeg"
            return fallback or "application/octet-stream"

        with self._kernel_mgr.session() as system:
            if system is None:
                return {
                    "record_id": record_id,
                    "error": "kernel_unavailable",
                    "detail": self._kernel_mgr.last_error(),
                    "status": 503,
                }
            metadata = system.get("storage.metadata")
            media = system.get("storage.media")
            if metadata is None:
                return {"record_id": record_id, "error": "metadata_unavailable", "status": 503}
            if media is None:
                return {"record_id": record_id, "error": "media_unavailable", "status": 503}
            record = metadata.get(record_id, None) if hasattr(metadata, "get") else None
            if record is None:
                return {"record_id": record_id, "error": "record_not_found", "status": 404}
            blob = _get_media_blob(media, record_id)
            if not blob:
                return {"record_id": record_id, "error": "media_not_found", "status": 404}
            record_type = str(record.get("record_type", "")) if isinstance(record, dict) else ""
            if record_type == "evidence.capture.frame":
                content_type = _guess_content_type(blob, record.get("content_type") if isinstance(record, dict) else None)
                return {"record_id": record_id, "content_type": content_type, "data": blob}
            container_type = None
            if isinstance(record, dict):
                container = record.get("container")
                if isinstance(container, dict):
                    container_type = container.get("type")
            frame = _extract_frame(blob, record if isinstance(record, dict) else {})
            if not frame:
                detail = "frame_extract_failed"
                if container_type:
                    detail = f"frame_extract_failed:{container_type}"
                return {
                    "record_id": record_id,
                    "error": "preview_unavailable",
                    "detail": detail,
                    "status": 422,
                }
            content_type = _guess_content_type(frame)
            return {"record_id": record_id, "content_type": content_type, "data": frame}

    def trace_process(
        self,
        record_id: str,
        *,
        allow_ocr: bool = True,
        allow_vlm: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        from autocapture_nx.kernel.providers import capability_providers as _capability_providers

        with self._kernel_mgr.session() as system:
            if system is None:
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "kernel_unavailable",
                    "detail": self._kernel_mgr.last_error(),
                }
            metadata = system.get("storage.metadata")
            media = system.get("storage.media")
            if metadata is None or media is None:
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "storage_unavailable",
                }
            record = metadata.get(record_id, None) if hasattr(metadata, "get") else None
            if record is None:
                return {"ok": False, "record_id": record_id, "error": "record_not_found"}
            record_type = str(record.get("record_type", "")) if isinstance(record, dict) else ""
            if not record_type.startswith("evidence.capture."):
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "unsupported_record_type",
                    "detail": record_type,
                }

            idle_window = float(system.config.get("runtime", {}).get("idle_window_s", 45)) if hasattr(system, "config") else 45.0
            idle_seconds = None
            can_run = True
            if not force:
                tracker = None
                try:
                    tracker = system.get("tracking.input")
                except Exception:
                    tracker = None
                if tracker is not None:
                    try:
                        idle_seconds = float(tracker.idle_seconds())
                    except Exception:
                        idle_seconds = 0.0
                    can_run = idle_seconds >= idle_window
                else:
                    assume_idle = bool(system.config.get("runtime", {}).get("activity", {}).get("assume_idle_when_missing", False))
                    can_run = assume_idle
            if not can_run:
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "user_active",
                    "idle_seconds": idle_seconds,
                    "idle_window_s": idle_window,
                }

            blob = _get_media_blob(media, record_id)
            if not blob:
                return {"ok": False, "record_id": record_id, "error": "media_not_found"}
            frame: bytes | None
            if record_type == "evidence.capture.frame":
                frame = blob
            else:
                frame = _extract_frame(blob, record)
            if frame is None:
                container_type = None
                if isinstance(record, dict):
                    container = record.get("container")
                    if isinstance(container, dict):
                        container_type = container.get("type")
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "frame_extract_failed",
                    "detail": container_type,
                }

            sst_cfg = {}
            if hasattr(system, "config"):
                sst_cfg = system.config.get("processing", {}).get("sst", {})
            pipeline = None
            if hasattr(system, "has") and system.has("processing.pipeline"):
                try:
                    pipeline = system.get("processing.pipeline")
                except Exception:
                    pipeline = None
            pipeline_enabled = bool(sst_cfg.get("enabled", True)) and pipeline is not None
            if pipeline is not None and pipeline_enabled and hasattr(pipeline, "process_record"):
                try:
                    result = pipeline.process_record(
                        record_id=record_id,
                        record=record,
                        frame_bytes=frame,
                        allow_ocr=bool(allow_ocr),
                        allow_vlm=bool(allow_vlm),
                        should_abort=None,
                        deadline_ts=None,
                    )
                except Exception as exc:
                    return {
                        "ok": False,
                        "record_id": record_id,
                        "error": "pipeline_failed",
                        "detail": str(exc),
                    }
                return {
                    "ok": True,
                    "record_id": record_id,
                    "processed": int(result.derived_records),
                    "derived_ids": list(result.derived_ids),
                    "pipeline_used": True,
                    "forced": bool(force),
                }

            if not allow_ocr and not allow_vlm:
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "extractors_disabled",
                }

            ocr = system.get("ocr.engine") if allow_ocr else None
            vlm = system.get("vision.extractor") if allow_vlm else None
            extractors: list[tuple[str, str, Any]] = []
            if allow_ocr and ocr is not None:
                for provider_id, extractor in _capability_providers(ocr, "ocr.engine"):
                    extractors.append(("ocr", provider_id, extractor))
            if allow_vlm and vlm is not None:
                for provider_id, extractor in _capability_providers(vlm, "vision.extractor"):
                    extractors.append(("vlm", provider_id, extractor))
            if not extractors:
                return {
                    "ok": False,
                    "record_id": record_id,
                    "error": "no_extractors_available",
                }

            config = system.config if hasattr(system, "config") else {}
            lexical = None
            vector = None
            if isinstance(config, dict) and config:
                try:
                    lexical, vector = build_indexes(config)
                except Exception:
                    lexical = None
                    vector = None
            event_builder = None
            try:
                event_builder = system.get("event.builder") if hasattr(system, "get") else None
            except Exception:
                event_builder = None

            run_id = record.get("run_id") if isinstance(record, dict) else None
            run_id = run_id or record_id.split("/", 1)[0]
            encoded_source = encode_record_id_component(record_id)
            derived_ids: list[str] = []
            processed = 0
            for kind, provider_id, extractor in extractors:
                provider_component = encode_record_id_component(str(provider_id))
                derived_id = f"{run_id}/derived.text.{kind}/{provider_component}/{encoded_source}"
                if metadata.get(derived_id):
                    continue
                try:
                    text = extract_text_payload(extractor.extract(frame))
                except Exception:
                    continue
                payload = build_text_record(
                    kind=kind,
                    text=text,
                    source_id=record_id,
                    source_record=record if isinstance(record, dict) else {},
                    provider_id=str(provider_id),
                    config=config if isinstance(config, dict) else {},
                    ts_utc=record.get("ts_utc") if isinstance(record, dict) else None,
                )
                if not payload:
                    continue
                if hasattr(metadata, "put_new"):
                    try:
                        metadata.put_new(derived_id, payload)
                    except Exception:
                        continue
                else:
                    metadata.put(derived_id, payload)
                if lexical is not None:
                    try:
                        lexical.index(derived_id, payload.get("text", ""))
                    except Exception:
                        pass
                if vector is not None:
                    try:
                        vector.index(derived_id, payload.get("text", ""))
                    except Exception:
                        pass
                processed += 1
                derived_ids.append(derived_id)
                edge_id = None
                try:
                    edge_id = derivation_edge_id(run_id, record_id, derived_id)
                    edge_payload = build_derivation_edge(
                        run_id=run_id,
                        parent_id=record_id,
                        child_id=derived_id,
                        relation_type="derived_from",
                        span_ref=payload.get("span_ref", {}),
                        method=kind,
                    )
                    if hasattr(metadata, "put_new"):
                        try:
                            metadata.put_new(edge_id, edge_payload)
                        except Exception:
                            edge_id = None
                    else:
                        metadata.put(edge_id, edge_payload)
                except Exception:
                    edge_id = None
                if event_builder is not None:
                    event_payload = dict(payload)
                    event_payload["derived_id"] = derived_id
                    if edge_id:
                        event_payload["derivation_edge_id"] = edge_id
                    parent_hash = record.get("content_hash") if isinstance(record, dict) else None
                    if parent_hash:
                        event_payload["parent_content_hash"] = parent_hash
                    ts_utc = payload.get("ts_utc")
                    try:
                        event_builder.journal_event("derived.extract", event_payload, event_id=derived_id, ts_utc=ts_utc)
                        event_builder.ledger_entry(
                            "derived.extract",
                            inputs=[record_id],
                            outputs=[derived_id] + ([edge_id] if edge_id else []),
                            payload=event_payload,
                            entry_id=derived_id,
                            ts_utc=ts_utc,
                        )
                    except Exception:
                        pass

            return {
                "ok": True,
                "record_id": record_id,
                "processed": processed,
                "derived_ids": derived_ids,
                "pipeline_used": False,
                "forced": bool(force),
            }

    def telemetry(self) -> dict[str, Any]:
        payload = telemetry_snapshot()
        if isinstance(payload, dict):
            payload["kernel_ready"] = self._kernel_mgr.kernel() is not None and self._kernel_mgr.last_error() is None
            payload["kernel_error"] = self._kernel_mgr.last_error()
        return payload

    def journal_tail(self, limit: int = 50) -> list[dict[str, Any]]:
        data_dir = Path(self._config.get("storage", {}).get("data_dir", "data"))
        journal_path = data_dir / "journal.ndjson"
        if not journal_path.exists():
            return []
        lines = journal_path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def bookmark_add(self, note: str, tags: list[str] | None = None) -> dict[str, Any]:
        note = str(note or "").strip()
        if not note:
            raise ValueError("bookmark_note_missing")
        payload = {
            "id": f"bookmark_{uuid.uuid4().hex}",
            "ts_utc": self._now_utc(),
            "note": note,
            "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()],
        }
        self._append_ndjson(self._bookmarks_path(), payload)
        try:
            with self._kernel_mgr.session() as system:
                builder = system.get("event.builder") if system and hasattr(system, "get") else None
                if builder is not None:
                    builder.journal_event("user.bookmark", payload, event_id=payload["id"], ts_utc=payload["ts_utc"])
        except Exception:
            pass
        return payload

    def bookmarks_list(self, limit: int = 20) -> dict[str, Any]:
        path = self._bookmarks_path()
        if not path.exists():
            return {"bookmarks": []}
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
        if limit > 0:
            items = items[-limit:]
        return {"bookmarks": items}

    def alerts(self, limit: int = 50) -> dict[str, Any]:
        from autocapture_nx.kernel.alerts import derive_alerts

        events = self.journal_tail(limit=limit)
        return {"alerts": derive_alerts(self._config, events)}

    def egress_requests(self) -> list[dict[str, Any]]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("egress.approval_store"):
                return []
            store = system.get("egress.approval_store")
            return store.list_requests() if hasattr(store, "list_requests") else []

    def egress_approve(self, approval_id: str, ttl_s: float | None = None) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("egress.approval_store"):
                raise KeyError("approval_store_missing")
            store = system.get("egress.approval_store")
            return store.approve(approval_id, ttl_s=ttl_s)

    def egress_deny(self, approval_id: str) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None or not system.has("egress.approval_store"):
                raise KeyError("approval_store_missing")
            store = system.get("egress.approval_store")
            store.deny(approval_id)
            return {"ok": True}

    def shutdown(self) -> None:
        self._kernel_mgr.shutdown()


def create_facade(
    *,
    persistent: bool = False,
    safe_mode: bool = False,
    start_conductor: bool = False,
    auto_start_capture: bool | None = None,
) -> UXFacade:
    return UXFacade(
        paths=default_config_paths(),
        safe_mode=safe_mode,
        persistent=persistent,
        start_conductor=start_conductor,
        auto_start_capture=auto_start_capture,
    )
