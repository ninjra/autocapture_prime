"""NX UX facade shared by CLI and Web console."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator, cast

from autocapture.indexing.factory import build_indexes
from autocapture.storage.stage1 import mark_stage1_and_retention
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
from autocapture_nx.kernel.activity_signal import is_activity_signal_fresh, load_activity_signal
from autocapture_nx.kernel.logging import JsonlLogger
from autocapture_nx.plugin_system.manager import PluginManager
from autocapture_nx.processing.idle import _extract_frame, _get_media_blob
from autocapture_nx.storage.stage1_derived_store import build_stage1_overlay_store


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _env_true(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


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
        self._last_error_monotonic: float = 0.0

    def _missing_capability_error(self, error: str | None) -> bool:
        text = str(error or "").strip()
        return text.startswith("Missing capability:")

    def _boot_retry_cooldown_s(self) -> float:
        raw = str(os.environ.get("AUTOCAPTURE_QUERY_BOOT_RETRY_COOLDOWN_S") or "").strip()
        try:
            val = float(raw) if raw else 30.0
        except Exception:
            val = 30.0
        return float(max(0.0, min(300.0, val)))

    def _should_skip_boot_retry(self) -> bool:
        if self._system is not None:
            return False
        if not self._missing_capability_error(self._last_error):
            return False
        if self._last_error_monotonic <= 0.0:
            return False
        elapsed = time.monotonic() - float(self._last_error_monotonic)
        return elapsed < self._boot_retry_cooldown_s()

    def warm_boot(self) -> dict[str, Any]:
        if not self._persistent:
            return {"ok": False, "error": "non_persistent_kernel"}
        with self._lock:
            if self._system is not None:
                return {"ok": True, "cached": True}
            if self._should_skip_boot_retry():
                return {"ok": False, "error": str(self._last_error or "kernel_boot_failed"), "cached": True}
            kernel = Kernel(self._paths, safe_mode=self._safe_mode)
            self._kernel = kernel
            try:
                self._system = kernel.boot(start_conductor=self._start_conductor)
                self._last_error = None
                self._last_error_monotonic = 0.0
                return {"ok": True, "cached": False}
            except Exception as exc:
                try:
                    kernel.shutdown()
                except Exception:
                    pass
                self._kernel = None
                self._system = None
                self._last_error = str(exc)
                self._last_error_monotonic = time.monotonic()
                return {"ok": False, "error": self._last_error, "cached": False}

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
                if self._should_skip_boot_retry():
                    yield None
                    return
                kernel = Kernel(self._paths, safe_mode=self._safe_mode)
                self._kernel = kernel
                try:
                    self._system = kernel.boot(start_conductor=self._start_conductor)
                    self._last_error = None
                    self._last_error_monotonic = 0.0
                except Exception as exc:
                    try:
                        kernel.shutdown()
                    except Exception:
                        pass
                    self._kernel = None
                    self._system = None
                    self._last_error = str(exc)
                    self._last_error_monotonic = time.monotonic()
                    yield None
                    return
        try:
            yield self._system
        finally:
            return

    def kernel(self) -> Kernel | None:
        return self._kernel

    def system(self) -> Any | None:
        # Return the already-booted system without forcing a boot.
        with self._lock:
            return self._system

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
            self._last_error_monotonic = 0.0


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
        self._warm_query_runtime()

    def _warm_query_runtime(self) -> None:
        if not self._persistent:
            return
        if not _env_true("AUTOCAPTURE_QUERY_METADATA_ONLY", default=False):
            return
        if not _env_true("AUTOCAPTURE_QUERY_WARM_BOOT", default=False):
            return
        try:
            _ = self._kernel_mgr.warm_boot()
        except Exception:
            return

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
        # OPS-06: always include DB schema/version snapshot without requiring heavy work.
        try:
            from autocapture_nx.kernel.db_status import db_status_snapshot, metadata_db_stability_snapshot

            db_status = db_status_snapshot(
                self._config,
                include_hash=True,
                include_pragmas=True,
                include_stability=True,
                stability_samples=2,
                stability_poll_interval_ms=50,
            )
            db_stability = metadata_db_stability_snapshot(self._config, sample_count=3, poll_interval_ms=100)
        except Exception:
            db_status = None
            db_stability = None
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
            failed = [str(getattr(c, "name", "")) for c in (checks or []) if getattr(c, "ok", True) is False]
            report = {
                "ok": ok,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "ok": bool(ok),
                    "code": "ok" if ok else "degraded",
                    "message": "ok" if ok else f"failed_checks={failed[:5]}",
                    "checks_total": int(len(checks or [])),
                    "checks_failed": int(len(failed)),
                },
                "checks": [check.__dict__ for check in checks],
            }
        if logger is not None:
            try:
                report.setdefault("logs", {})["core_jsonl"] = logger.path
            except Exception:
                pass
        if db_status is not None:
            report["db_status"] = db_status
        if db_stability is not None:
            report["db_stability"] = db_stability
        return report

    def diagnostics_bundle_create(self) -> dict[str, Any]:
        from autocapture_nx.kernel.diagnostics_bundle import create_diagnostics_bundle

        # Avoid heavy work: reuse doctor_report and export with redaction.
        report = self.doctor_report()
        result = create_diagnostics_bundle(config=self._config, doctor_report=report)
        return {"ok": True, "path": result.path, "sha256": result.bundle_sha256, "manifest": result.manifest}

    def self_test(self) -> dict[str, Any]:
        """OPS-07: low-friction, offline self-test (boot + ledger write + verify)."""
        import time

        started = time.perf_counter()
        boot_ok = False
        plugin_count = 0
        ledger_head = None
        error: str | None = None
        boot_ms = None
        ledger_ms = None
        verify_ms = None
        try:
            boot_start = time.perf_counter()
            with self._kernel_mgr.session() as system:
                boot_ok = system is not None
                boot_ms = int(round((time.perf_counter() - boot_start) * 1000.0))
                try:
                    plugin_count = int(len(getattr(system, "plugins", []) or []))
                except Exception:
                    plugin_count = 0
                # Append a deterministic ledger entry (best-effort; do not fail open).
                ledger_start = time.perf_counter()
                try:
                    builder = system.get("event.builder") if system and hasattr(system, "get") else None
                    if builder is not None and hasattr(builder, "ledger_entry"):
                        builder.ledger_entry(
                            "operator.self_test",
                            inputs=[],
                            outputs=[],
                            payload={"event": "self_test"},
                        )
                        try:
                            ledger_head = builder.ledger_head()
                        except Exception:
                            ledger_head = None
                finally:
                    ledger_ms = int(round((time.perf_counter() - ledger_start) * 1000.0))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        verify_start = time.perf_counter()
        ledger_report = self.verify_ledger()
        anchors_report = self.verify_anchors()
        verify_ms = int(round((time.perf_counter() - verify_start) * 1000.0))

        ok = bool(boot_ok) and bool(ledger_report.get("ok")) and bool(anchors_report.get("ok"))
        return {
            "ok": ok,
            "boot_ok": bool(boot_ok),
            "plugin_count": int(plugin_count),
            "ledger_head": ledger_head,
            "ledger": ledger_report,
            "anchors": anchors_report,
            "timings_ms": {
                "boot_ms": boot_ms,
                "ledger_write_ms": ledger_ms,
                "verify_ms": verify_ms,
                "total_ms": int(round((time.perf_counter() - started) * 1000.0)),
            },
            "error": error,
        }

    def resolve_citations(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            validator = system.get("citation.validator")
            return validator.resolve(citations)

    def verify_citations(self, citations: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.resolve_citations(citations)
        return {"ok": bool(result.get("ok")), "errors": result.get("errors", [])}

    def config_get(self) -> dict[str, Any]:
        return dict(self._config)

    def config_diff(self) -> dict[str, Any]:
        """UX-09: deterministic diff viewer (default vs user overrides vs effective)."""

        def _load(path: Path) -> dict[str, Any]:
            if not path.exists():
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}

        default_cfg = _load(self._paths.default_path)
        user_cfg = _load(self._paths.user_path)
        effective = dict(self._config)

        def _walk(prefix: str, a: Any, b: Any, out: list[dict[str, Any]]) -> None:
            if isinstance(a, dict) and isinstance(b, dict):
                keys = sorted({*a.keys(), *b.keys()}, key=lambda k: str(k))
                for k in keys:
                    kp = f"{prefix}.{k}" if prefix else str(k)
                    _walk(kp, a.get(k, _MISSING), b.get(k, _MISSING), out)
                return
            if a is _MISSING and b is _MISSING:
                return
            if a == b:
                return
            out.append({"path": prefix, "from": a if a is not _MISSING else None, "to": b if b is not _MISSING else None})

        diff_default_to_effective: list[dict[str, Any]] = []
        _walk("", default_cfg, effective, diff_default_to_effective)
        diff_default_to_effective.sort(key=lambda r: str(r.get("path") or ""))

        diff_user_to_effective: list[dict[str, Any]] = []
        _walk("", user_cfg, effective, diff_user_to_effective)
        diff_user_to_effective.sort(key=lambda r: str(r.get("path") or ""))

        return {
            "ok": True,
            "default_path": str(self._paths.default_path),
            "user_path": str(self._paths.user_path),
            "diff_default_to_effective": diff_default_to_effective,
            "diff_user_to_effective": diff_user_to_effective,
        }

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

    def config_set(self, patch: dict[str, Any], *, confirm: str = "") -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("config_patch_invalid")
        # Misclick-resistant dangerous toggles: require typed confirmation when enabling.
        def _walk(obj: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
            if not isinstance(obj, dict):
                return [(prefix, obj)]
            out: list[tuple[tuple[str, ...], Any]] = []
            for k, v in obj.items():
                out.extend(_walk(v, prefix + (str(k),)))
            return out

        dangerous_enable_paths = {
            ("privacy", "egress", "allow_raw_egress"),
            ("privacy", "cloud", "enabled"),
            ("privacy", "cloud", "allow_images"),
        }
        enabling = []
        for path, value in _walk(patch):
            if path in dangerous_enable_paths and bool(value) is True:
                enabling.append(".".join(path))
        if enabling:
            if str(confirm).strip() != "I UNDERSTAND":
                return {"ok": False, "error": "confirmation_required", "required": "I UNDERSTAND", "paths": enabling}

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

    def plugins_plan(self) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return manager.plugins_plan()

    def plugins_apply(self, plan_hash: str, *, enable: list[str] | None = None, disable: list[str] | None = None) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.plugins_apply(plan_hash=str(plan_hash), enable=enable, disable=disable)
        if bool(result.get("ok")):
            self.reload_config()
        return result

    def plugins_install_local(self, path: str, *, dry_run: bool = True) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.install_local(path, dry_run=dry_run)
        # Installing updates config + lockfile; reload effective config.
        if bool(result.get("ok")) and not dry_run:
            self.reload_config()
        return result

    def plugins_lock_snapshot(self, reason: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return manager.lockfile_snapshot(reason=str(reason))

    def plugins_lock_rollback(self, snapshot_path: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.lockfile_rollback(snapshot_path)
        if bool(result.get("ok")):
            self.reload_config()
        return result

    def plugins_lifecycle_state(self, plugin_id: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return manager.lifecycle_state(plugin_id)

    def plugins_permissions_digest(self, plugin_id: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return manager.permissions_digest(plugin_id)

    def plugins_approve_permissions(self, plugin_id: str, accept_digest: str, *, confirm: str = "") -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.approve_permissions_confirm(plugin_id, accept_digest=str(accept_digest), confirm=str(confirm))
        if bool(result.get("ok")):
            self.reload_config()
        return result

    def plugins_lock_diff(self, a_path: str, b_path: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        return manager.lockfile_diff(str(a_path), str(b_path))

    def plugins_update_lock(self, plugin_id: str, *, reason: str = "update") -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.update_lock_entry(plugin_id, reason=str(reason))
        if bool(result.get("ok")):
            self.reload_config()
        return result

    def plugins_quarantine(self, plugin_id: str, reason: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.quarantine(plugin_id, reason=str(reason))
        if bool(result.get("ok")):
            self.reload_config()
        return result

    def plugins_unquarantine(self, plugin_id: str) -> dict[str, Any]:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        result = manager.unquarantine(plugin_id)
        if bool(result.get("ok")):
            self.reload_config()
        return result

    def plugins_logs(self, plugin_id: str, *, limit: int = 80) -> dict[str, Any]:
        # EXT-09: return per-plugin host_runner logs (best-effort, sanitized).
        limit = max(1, min(400, int(limit or 80)))
        data_dir = Path(str(self._config.get("storage", {}).get("data_dir", "data")))
        filename = f"plugin_host_{plugin_id}.log"

        run_ids: list[str] = []
        config_run_id = str(self._config.get("runtime", {}).get("run_id") or "").strip()
        if config_run_id:
            run_ids.append(config_run_id)
        status_run_id = str(self.status().get("run_id") or "").strip()
        if status_run_id:
            run_ids.append(status_run_id)
        run_ids.append("run")
        seen_run_ids: set[str] = set()
        ordered_run_ids: list[str] = []
        for run_id in run_ids:
            if run_id in seen_run_ids:
                continue
            seen_run_ids.add(run_id)
            ordered_run_ids.append(run_id)

        def _sanitize_plugin_id(value: str) -> str:
            raw = value.strip() or "plugin"
            raw = raw.replace("\\", "_").replace("/", "_")
            return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in raw)

        candidate_paths: list[Path] = []
        env_host_log_dir = os.getenv("AUTOCAPTURE_HOST_LOG_DIR", "").strip()
        if env_host_log_dir:
            candidate_paths.append(Path(env_host_log_dir) / filename)
        for run_id in ordered_run_ids:
            candidate_paths.append(data_dir / "runs" / run_id / filename)
        hosting_cfg = self._config.get("plugins", {}).get("hosting", {})
        hosting_cache_raw = hosting_cfg.get("cache_dir") if isinstance(hosting_cfg, dict) else None
        cache_root = Path(str(hosting_cache_raw)) if hosting_cache_raw else data_dir / "cache" / "plugins"
        plugin_cache_root = cache_root / _sanitize_plugin_id(plugin_id)
        candidate_paths.append(plugin_cache_root / "tmp" / filename)
        candidate_paths.append(plugin_cache_root / filename)

        unique_paths: list[Path] = []
        seen_paths: set[str] = set()
        for path in candidate_paths:
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            unique_paths.append(path)

        existing_paths = [path for path in unique_paths if path.exists()]
        if not existing_paths:
            primary = unique_paths[0] if unique_paths else data_dir / "runs" / "run" / filename
            return {
                "ok": True,
                "plugin_id": plugin_id,
                "path": str(primary),
                "lines": [],
                "missing": True,
                "searched_paths": [str(path) for path in unique_paths],
            }
        chosen_path: Path | None = None
        chosen_lines: list[str] = []
        for candidate in unique_paths:
            if not candidate.exists():
                continue
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = lines[-limit:]
            redacted: list[str] = []
            for line in tail:
                text = str(line)
                if "OPENAI_API_KEY" in text or "Authorization:" in text:
                    continue
                redacted.append(text[:2000])
            if chosen_path is None:
                chosen_path = candidate
                chosen_lines = redacted
            if redacted:
                chosen_path = candidate
                chosen_lines = redacted
                break
        path = chosen_path or existing_paths[0]
        redacted = chosen_lines
        return {"ok": True, "plugin_id": plugin_id, "path": str(path), "lines": redacted, "missing": False}

    def plugins_capabilities_matrix(self) -> dict[str, Any]:
        # EXT-12: stable capabilities matrix derived from manifests.
        plan = self.plugins_plan()
        return {"ok": True, "capabilities": plan.get("capabilities", {}), "conflicts": plan.get("conflicts", {})}

    def plugins_reload(self, plugin_ids: list[str] | None = None) -> dict[str, Any]:
        kernel = self._kernel_mgr.kernel()
        if kernel is None:
            raise RuntimeError("kernel_not_running")
        return kernel.reload_plugins(plugin_ids=plugin_ids)

    def operator_reindex(self) -> dict[str, Any]:
        from autocapture_nx.kernel.operator_ledger import record_operator_action

        return record_operator_action(config=self._config, action="reindex", payload={"scheduled": True})

    def operator_vacuum(self, *, include_state: bool = True) -> dict[str, Any]:
        import sqlite3

        from autocapture_nx.kernel.operator_ledger import record_operator_action

        storage = self._config.get("storage", {}) if isinstance(self._config, dict) else {}
        paths = [
            ("metadata", storage.get("metadata_path", "data/metadata.db")),
            ("lexical", storage.get("lexical_path", "data/lexical.db")),
            ("vector", storage.get("vector_path", "data/vector.db")),
        ]
        if include_state:
            paths.extend(
                [
                    ("state_tape", storage.get("state_tape_path", "data/state/state_tape.db")),
                    ("state_vector", storage.get("state_vector_path", "data/state/state_vector.db")),
                ]
            )
        vacuumed: list[str] = []
        for _name, raw in paths:
            if not raw:
                continue
            try:
                con = sqlite3.connect(str(raw))
                try:
                    con.execute("VACUUM")
                    con.commit()
                finally:
                    con.close()
                vacuumed.append(str(raw))
            except Exception:
                continue
        return record_operator_action(config=self._config, action="vacuum", payload={"vacuumed": vacuumed})

    def operator_quarantine(self, plugin_id: str, *, reason: str) -> dict[str, Any]:
        from autocapture_nx.kernel.operator_ledger import record_operator_action

        result = self.plugins_quarantine(plugin_id, reason)
        record_operator_action(config=self._config, action="quarantine", payload={"plugin_id": plugin_id, "reason": reason})
        return result

    def operator_rollback_locks(self, snapshot_path: str) -> dict[str, Any]:
        from autocapture_nx.kernel.operator_ledger import record_operator_action

        result = self.plugins_lock_rollback(snapshot_path)
        record_operator_action(config=self._config, action="rollback-locks", payload={"snapshot_path": snapshot_path})
        return result

    def _kernel_boot_failure_query_result(self, text: str, error: str | None) -> dict[str, Any]:
        detail = str(error or "kernel_boot_failed").strip() or "kernel_boot_failed"
        return {
            "ok": False,
            "error": "kernel_boot_failed",
            "query": str(text or ""),
            "answer": {
                "state": "degraded",
                "summary": "Query unavailable because runtime boot failed.",
                "display": {
                    "summary": "Query unavailable because runtime boot failed.",
                    "topic": "runtime",
                    "confidence_pct": 0.0,
                    "bullets": [
                        "Kernel boot failed before query execution.",
                        f"detail: {detail[:240]}",
                    ],
                },
                "claims": [],
            },
            "processing": {
                "extraction": {
                    "allowed": False,
                    "ran": False,
                    "blocked": True,
                    "blocked_reason": "kernel_boot_failed",
                    "scheduled_extract_job_id": "",
                },
                "query_trace": {
                    "query_run_id": f"qry_boot_fail_{uuid.uuid4().hex[:12]}",
                    "stage_ms": {"total": 0.0},
                    "error": "kernel_boot_failed",
                    "error_detail": detail,
                },
            },
            "scheduled_extract_job_id": "",
        }

    def _missing_query_capabilities_result(self, text: str, missing: list[str]) -> dict[str, Any]:
        missing_caps = [str(item).strip() for item in missing if str(item).strip()]
        return {
            "ok": False,
            "error": "query_capability_missing",
            "query": str(text or ""),
            "answer": {
                "state": "degraded",
                "summary": "Query unavailable because required capabilities are missing.",
                "display": {
                    "summary": "Query unavailable because required capabilities are missing.",
                    "topic": "runtime",
                    "confidence_pct": 0.0,
                    "bullets": [
                        "Required query capabilities are unavailable.",
                        f"missing: {', '.join(missing_caps[:8])}",
                    ],
                },
                "claims": [],
            },
            "processing": {
                "extraction": {
                    "allowed": False,
                    "ran": False,
                    "blocked": True,
                    "blocked_reason": "query_capability_missing",
                    "scheduled_extract_job_id": "",
                },
                "query_trace": {
                    "query_run_id": f"qry_cap_missing_{uuid.uuid4().hex[:12]}",
                    "stage_ms": {"total": 0.0},
                    "error": "query_capability_missing",
                    "missing_capabilities": missing_caps,
                },
            },
            "scheduled_extract_job_id": "",
        }

    @staticmethod
    def _missing_capabilities_from_error(error: str | None) -> list[str]:
        text = str(error or "").strip()
        if not text:
            return []
        prefix = "Missing capability:"
        if not text.startswith(prefix):
            return []
        raw = str(text[len(prefix) :]).strip()
        raw = raw.split(" plugin_load_failures=", 1)[0].strip()
        raw = raw.rstrip(".")
        if not raw:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for part in raw.split(","):
            cap = str(part or "").strip()
            if not cap or cap in seen:
                continue
            seen.add(cap)
            out.append(cap)
        return out

    def query(self, text: str, *, schedule_extract: bool = False) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            if system is None:
                boot_error = self._kernel_mgr.last_error()
                missing_caps_boot = self._missing_capabilities_from_error(boot_error)
                if missing_caps_boot:
                    return self._missing_query_capabilities_result(text, missing_caps_boot)
                return self._kernel_boot_failure_query_result(text, boot_error)
            required_caps = (
                "storage.metadata",
                "retrieval.strategy",
                "answer.builder",
                "time.intent_parser",
            )
            missing_caps: list[str] = []
            for capability in required_caps:
                try:
                    if hasattr(system, "has"):
                        if not bool(system.has(capability)):
                            missing_caps.append(capability)
                            continue
                    _ = system.get(capability)
                except Exception:
                    missing_caps.append(capability)
            if missing_caps:
                return self._missing_query_capabilities_result(text, missing_caps)
            _ = schedule_extract
            return run_query(system, text, schedule_extract=False)

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

    def batch_run(
        self,
        *,
        max_loops: int = 500,
        sleep_ms: int = 200,
        require_idle: bool = True,
    ) -> dict[str, Any]:
        from autocapture_nx.runtime.batch import run_processing_batch

        with self._kernel_mgr.session() as system:
            return run_processing_batch(
                system,
                max_loops=int(max_loops),
                sleep_ms=int(sleep_ms),
                require_idle=bool(require_idle),
            )

    def keys_rotate(self) -> dict[str, Any]:
        from autocapture_nx.kernel.key_rotation import rotate_keys

        with self._kernel_mgr.session() as system:
            return rotate_keys(system)

    def status(self) -> dict[str, Any]:
        # Status must be lightweight: do not force a kernel boot just to answer.
        system = self._kernel_mgr.system()
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
        # PERF-08: resource snapshot + governor state (best-effort; do not boot kernel).
        resources = None
        governor = None
        try:
            from autocapture.runtime.resources import sample_resources

            snap = sample_resources()
            resources = {
                "cpu_utilization": snap.cpu_utilization,
                "ram_utilization": snap.ram_utilization,
            }
        except Exception:
            resources = None
        if system is not None and hasattr(system, "has") and system.has("runtime.governor"):
            try:
                gov = system.get("runtime.governor")
            except Exception:
                gov = None
            if gov is not None:
                try:
                    # Avoid expensive signal collection: expose budget snapshot and preempt state only.
                    bs = gov.budget_snapshot() if hasattr(gov, "budget_snapshot") else None
                    governor = {
                        "idle_window_s": getattr(gov, "idle_window_s", None),
                        "suspend_workers": getattr(gov, "suspend_workers", None),
                        "budget": asdict(bs) if bs is not None else None,
                        "should_preempt": bool(gov.should_preempt()) if hasattr(gov, "should_preempt") else None,
                    }
                except Exception:
                    governor = None
        db_stability = None
        try:
            from autocapture_nx.kernel.db_status import metadata_db_stability_snapshot

            db_stability = metadata_db_stability_snapshot(self._config, sample_count=2, poll_interval_ms=25)
        except Exception:
            db_stability = None
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
            "resources": resources,
            "governor": governor,
            "db_stability": db_stability,
            "kernel_ready": system is not None,
            "kernel_error": kernel_error,
        }

    def run_detail(self) -> dict[str, Any]:
        """UX-03: run/job detail payload with provenance anchors."""
        system = self._kernel_mgr.system()
        builder = system.get("event.builder") if system and hasattr(system, "get") else None
        run_id = ""
        ledger_head = None
        last_anchor = None
        try:
            run_id = builder.run_id if builder is not None else ""
        except Exception:
            run_id = ""
        try:
            ledger_head = builder.ledger_head() if builder is not None else None
        except Exception:
            ledger_head = None
        try:
            last_anchor = builder.last_anchor() if builder is not None and hasattr(builder, "last_anchor") else None
        except Exception:
            last_anchor = None
        lockfile = None
        try:
            manager = PluginManager(self._config, safe_mode=self._safe_mode)
            lock_path = manager._lockfile_path()  # noqa: SLF001
            from autocapture_nx.kernel.hashing import sha256_file

            lockfile = {"path": str(lock_path), "sha256": sha256_file(lock_path) if lock_path.exists() else None}
        except Exception:
            lockfile = None
        return {
            "ok": True,
            "run_id": run_id,
            "data_dir": str(self._config.get("storage", {}).get("data_dir", "data")),
            "ledger_head": ledger_head,
            "last_anchor": last_anchor,
            "lockfile": lockfile,
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
        if system is None:
            # Lightweight path: do not force a kernel boot for status UI/API.
            telemetry = telemetry_snapshot()
            latest = telemetry.get("latest", {}) if isinstance(telemetry, dict) else {}
            watchdog = latest.get("processing.watchdog") if isinstance(latest, dict) else None
            return {"mode": None, "paused": None, "reason": None, "watchdog": watchdog}
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

    def _start_components(self) -> dict[str, Any]:
        """Start capture-related components.

        Fail closed for soak/ops: if required components can't start or the kernel
        can't boot, bubble up a structured error so scripts don't "fake run".
        """

        errors: list[dict[str, Any]] = []
        started_names: list[str] = []
        kernel_error = None
        # Ensure these are always defined, even if the session block errors early.
        # This prevents ambiguous soak output like present={} wanted={} which hides
        # whether capture was configured and which capabilities were missing.
        present: dict[str, Any] = {
            "capture.source": False,
            "capture.screenshot": False,
            "capture.audio": False,
            "tracking.input": False,
            "window.metadata": False,
            "tracking.cursor": False,
            "tracking.clipboard": False,
            "tracking.file_activity": False,
        }
        wanted: dict[str, Any] = {}
        # Compute "wanted" from config outside the kernel session so it is always
        # populated even when boot fails.
        capture_cfg = self._config.get("capture") if isinstance(self._config.get("capture"), dict) else {}
        want_screenshot = bool((capture_cfg.get("screenshot") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        want_audio = bool((capture_cfg.get("audio") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        want_source = bool((capture_cfg.get("video") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        # Trackers are started only if enabled in config to reduce overhead during soak.
        input_cfg = capture_cfg.get("input_tracking", {}) if isinstance(capture_cfg, dict) else {}
        input_mode = str(input_cfg.get("mode") or "").strip().lower()
        want_input = bool(input_mode and input_mode not in {"off", "disabled", "none"})
        want_window_meta = bool((capture_cfg.get("window_metadata") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        want_cursor = bool((capture_cfg.get("cursor") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        want_clipboard = bool((capture_cfg.get("clipboard") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        want_file_activity = bool((capture_cfg.get("file_activity") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
        wanted = {
            "capture.source": want_source,
            "capture.screenshot": want_screenshot,
            "capture.audio": want_audio,
            "tracking.input": want_input,
            "window.metadata": want_window_meta,
            "tracking.cursor": want_cursor,
            "tracking.clipboard": want_clipboard,
            "tracking.file_activity": want_file_activity,
        }

        def _providers(obj: Any) -> list[str] | None:
            # Best-effort introspection for capability proxies (helps diagnose
            # "no providers" cases where hasattr/getattr can raise).
            if obj is None:
                return None
            if hasattr(obj, "provider_ids") and callable(getattr(obj, "provider_ids", None)):
                try:
                    ids = obj.provider_ids()
                    if isinstance(ids, list):
                        return [str(x) for x in ids]
                except Exception:
                    return None
            if hasattr(obj, "plugin_id"):
                try:
                    pid = getattr(obj, "plugin_id")
                    if isinstance(pid, str) and pid:
                        return [pid]
                except Exception:
                    return None
            return None

        def _startable(obj: Any) -> tuple[bool, str | None]:
            if obj is None:
                return (False, "missing")
            try:
                attr = getattr(obj, "start", None)
            except Exception as exc:
                return (False, f"start_attr_error:{type(exc).__name__}:{exc}")
            if not callable(attr):
                return (False, "no_start_method")
            return (True, None)

        with self._kernel_mgr.session() as system:
            if system is None:
                kernel_error = self._kernel_mgr.last_error()
                return {
                    "ok": False,
                    "error": "kernel_boot_failed",
                    "kernel_error": kernel_error,
                    "started": [],
                    "errors": [],
                    "present": present,
                    "wanted": wanted,
                }

            # Pull capabilities with "has" checks where possible to avoid raising when a
            # capability is not registered.
            capture = system.get("capture.source") if hasattr(system, "has") and system.has("capture.source") else None
            screenshot = system.get("capture.screenshot") if hasattr(system, "has") and system.has("capture.screenshot") else None
            audio = system.get("capture.audio") if hasattr(system, "has") and system.has("capture.audio") else None
            input_tracker = system.get("tracking.input") if hasattr(system, "has") and system.has("tracking.input") else None
            window_meta = system.get("window.metadata") if hasattr(system, "has") and system.has("window.metadata") else None
            cursor_tracker = system.get("tracking.cursor") if hasattr(system, "has") and system.has("tracking.cursor") else None
            clipboard = system.get("tracking.clipboard") if hasattr(system, "has") and system.has("tracking.clipboard") else None
            file_activity = system.get("tracking.file_activity") if hasattr(system, "has") and system.has("tracking.file_activity") else None

            present = {
                "capture.source": {"present": capture is not None, "providers": _providers(capture), "startable": _startable(capture)[0]},
                "capture.screenshot": {"present": screenshot is not None, "providers": _providers(screenshot), "startable": _startable(screenshot)[0]},
                "capture.audio": {"present": audio is not None, "providers": _providers(audio), "startable": _startable(audio)[0]},
                "tracking.input": {"present": input_tracker is not None, "providers": _providers(input_tracker), "startable": _startable(input_tracker)[0]},
                "window.metadata": {"present": window_meta is not None, "providers": _providers(window_meta), "startable": _startable(window_meta)[0]},
                "tracking.cursor": {"present": cursor_tracker is not None, "providers": _providers(cursor_tracker), "startable": _startable(cursor_tracker)[0]},
                "tracking.clipboard": {"present": clipboard is not None, "providers": _providers(clipboard), "startable": _startable(clipboard)[0]},
                "tracking.file_activity": {"present": file_activity is not None, "providers": _providers(file_activity), "startable": _startable(file_activity)[0]},
            }

            # (name, component, should_start, required)
            #
            # Trackers are optional for capture+ingest: capture must never be blocked due
            # to missing peripheral metadata providers. However, they still must respect
            # config "wanted" flags (do not start when disabled).
            components: list[tuple[str, Any, bool, bool]] = [
                ("capture.source", capture, want_source, want_source),
                ("capture.screenshot", screenshot, want_screenshot, want_screenshot),
                ("capture.audio", audio, want_audio, want_audio),
                ("tracking.input", input_tracker, want_input, False),
                ("window.metadata", window_meta, want_window_meta, False),
                ("tracking.cursor", cursor_tracker, want_cursor, False),
                ("tracking.clipboard", clipboard, want_clipboard, False),
                ("tracking.file_activity", file_activity, want_file_activity, False),
            ]

            for name, component, should_start, required in components:
                if component is None:
                    if required:
                        errors.append({"component": name, "error": "missing"})
                    continue
                if not should_start:
                    continue
                ok_start, start_issue = _startable(component)
                if not ok_start:
                    if required:
                        errors.append({"component": name, "error": start_issue or "not_startable"})
                    continue
                try:
                    start_fn = getattr(component, "start")
                except Exception as exc:
                    if required:
                        errors.append({"component": name, "error": f"start_attr_error:{type(exc).__name__}:{exc}"})
                    continue
                try:
                    start_fn()
                    started_names.append(name)
                except Exception as exc:
                    if required:
                        errors.append({"component": name, "error": f"{type(exc).__name__}: {exc}"})
                    continue

        started = bool(started_names)
        self._run_active = started
        if errors:
            return {
                "ok": False,
                "error": "component_start_failed",
                "started": started_names,
                "errors": errors,
                "present": present,
                "wanted": wanted,
            }
        if not started:
            return {
                "ok": False,
                "error": "no_components_started",
                "started": [],
                "errors": [],
                "present": present,
                "wanted": wanted,
            }
        return {"ok": True, "started": started_names, "errors": [], "present": present, "wanted": wanted}

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
            capture_privacy_cfg = privacy_cfg.get("capture", {}) if isinstance(privacy_cfg, dict) else {}
            require_consent = bool(capture_privacy_cfg.get("require_consent", True))
            if require_consent:
                from autocapture_nx.kernel.consent import load_capture_consent

                storage_cfg = self._config.get("storage", {}) if isinstance(self._config, dict) else {}
                configured_data_dir = str(storage_cfg.get("data_dir", "data")) if isinstance(storage_cfg, dict) else "data"
                data_dir = str(os.environ.get("AUTOCAPTURE_DATA_DIR") or configured_data_dir)
                consent = load_capture_consent(data_dir=data_dir)
                if not consent.accepted:
                    return {"ok": False, "error": "consent_required", "running": False}
        except Exception:
            return {"ok": False, "error": "consent_check_failed", "running": False}
        start_result_raw = self._start_components()
        if isinstance(start_result_raw, dict):
            start_result = start_result_raw
        else:
            start_result = {
                "ok": bool(self._run_active),
                "started": [],
                "error": "capture_start_failed",
            }
        if not bool(start_result.get("ok", self._run_active)):
            return {"ok": False, "error": str(start_result.get("error") or "capture_start_failed"), "details": start_result, "running": False}
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
        return {"ok": True, "running": True, "started": start_result.get("started")}

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

    def run_resume(self) -> dict[str, Any]:
        """UX-02: idempotent resume (do not duplicate capture.start ledger entries)."""
        if not self._capture_controls_enabled():
            return {"ok": False, "error": "capture_controls_disabled"}
        with self._pause_lock:
            self._clear_pause_locked()
        if self._run_active:
            return {"ok": True, "running": True, "resumed": False}
        start_result = self._start_components()
        if not bool(start_result.get("ok", False)):
            error = str(start_result.get("error") or "capture_start_failed")
            if error in {"no_components_started", "capture_disabled"}:
                return {"ok": True, "running": False, "resumed": False, "details": start_result}
            return {"ok": False, "error": error, "details": start_result, "running": False}
        with self._kernel_mgr.session() as system:
            builder = system.get("event.builder") if system and hasattr(system, "get") else None
            if builder is not None and hasattr(builder, "ledger_entry"):
                try:
                    builder.ledger_entry(
                        "operator.capture.resume",
                        inputs=[],
                        outputs=[],
                        payload={"event": "capture.resume"},
                    )
                except Exception:
                    pass
        return {"ok": True, "running": True, "resumed": True}

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
            anchor_path = Path(path) if path else Path(anchor_cfg.get("path", "anchor/anchors.ndjson"))
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
            anchor_path = Path(storage_cfg.get("anchor", {}).get("path", "anchor/anchors.ndjson"))
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
            anchor_path = Path(storage_cfg.get("anchor", {}).get("path", "anchor/anchors.ndjson"))
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

        with self._kernel_mgr.session() as system:
            keyring = system.get("storage.keyring") if system.has("storage.keyring") else None
            return asdict(replay_bundle(bundle_path, keyring=keyring))

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
            event_builder = None
            try:
                event_builder = system.get("event.builder") if hasattr(system, "get") else None
            except Exception:
                event_builder = None
            logger = None
            try:
                logger = system.get("observability.logger") if hasattr(system, "get") else None
            except Exception:
                logger = None
            stage1_store, _stage1_derived = build_stage1_overlay_store(
                config=system.config if hasattr(system, "config") else {},
                metadata=metadata,
                logger=logger,
            )

            def _mark_stage1_retention(reason: str) -> dict[str, Any] | None:
                try:
                    return mark_stage1_and_retention(
                        stage1_store,
                        record_id,
                        record if isinstance(record, dict) else {},
                        ts_utc=(record.get("ts_utc") if isinstance(record, dict) else None),
                        reason=reason,
                        event_builder=event_builder,
                        logger=logger,
                    )
                except Exception:
                    return None

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
                    signal = None
                    try:
                        signal = load_activity_signal(system.config)
                    except Exception:
                        signal = None
                    if signal is not None and is_activity_signal_fresh(signal, system.config):
                        idle_seconds = float(signal.idle_seconds)
                        can_run = idle_seconds >= idle_window
                    else:
                        can_run = False
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
                marker = _mark_stage1_retention("trace_process")
                return {
                    "ok": True,
                    "record_id": record_id,
                    "processed": int(result.derived_records),
                    "derived_ids": list(result.derived_ids),
                    "pipeline_used": True,
                    "forced": bool(force),
                    "stage1_marker": (marker or {}).get("stage1_record_id") if isinstance(marker, dict) else None,
                    "retention_marker": (marker or {}).get("retention_record_id") if isinstance(marker, dict) else None,
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

            marker = _mark_stage1_retention("trace_process")
            return {
                "ok": True,
                "record_id": record_id,
                "processed": processed,
                "derived_ids": derived_ids,
                "pipeline_used": False,
                "forced": bool(force),
                "stage1_marker": (marker or {}).get("stage1_record_id") if isinstance(marker, dict) else None,
                "retention_marker": (marker or {}).get("retention_record_id") if isinstance(marker, dict) else None,
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
