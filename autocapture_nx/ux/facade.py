"""NX UX facade shared by CLI and Web console."""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator

from autocapture_nx.kernel.config import ConfigPaths, load_config, reset_user_config, restore_user_config, validate_config
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.query import run_query
from autocapture_nx.kernel.telemetry import telemetry_snapshot
from autocapture_nx.plugin_system.manager import PluginManager


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

    @contextmanager
    def session(self) -> Iterator[Any]:
        if not self._persistent:
            kernel = Kernel(self._paths, safe_mode=self._safe_mode)
            system = kernel.boot(start_conductor=self._start_conductor)
            try:
                yield system
            finally:
                kernel.shutdown()
            return
        with self._lock:
            if self._kernel is None:
                self._kernel = Kernel(self._paths, safe_mode=self._safe_mode)
                self._system = self._kernel.boot(start_conductor=self._start_conductor)
        try:
            yield self._system
        finally:
            return

    def kernel(self) -> Kernel | None:
        return self._kernel

    def shutdown(self) -> None:
        with self._lock:
            if self._kernel is None:
                return
            self._kernel.shutdown()
            self._kernel = None
            self._system = None


class UXFacade:
    def __init__(
        self,
        *,
        paths: ConfigPaths | None = None,
        safe_mode: bool = False,
        persistent: bool = False,
        start_conductor: bool = False,
    ) -> None:
        self._paths = paths or default_config_paths()
        self._safe_mode = safe_mode
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

    @property
    def config(self) -> dict[str, Any]:
        return dict(self._config)

    def reload_config(self) -> dict[str, Any]:
        self._config = load_config(self._paths, safe_mode=self._safe_mode)
        return dict(self._config)

    def doctor_report(self) -> dict[str, Any]:
        kernel = self._kernel_mgr.kernel()
        if kernel is None:
            kernel = Kernel(self._paths, safe_mode=self._safe_mode)
            kernel.boot(start_conductor=False)
            checks = kernel.doctor()
            kernel.shutdown()
        else:
            checks = kernel.doctor()
        ok = all(check.ok for check in checks)
        return {
            "ok": ok,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "checks": [check.__dict__ for check in checks],
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
        self._paths.user_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.user_path.write_text(json.dumps(user_cfg, indent=2, sort_keys=True), encoding="utf-8")
        try:
            self.reload_config()
        except Exception as exc:
            self._paths.user_path.write_text(prior_text, encoding="utf-8")
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
        self._paths.user_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.user_path.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
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

        return build_settings_schema(self._paths.schema_path, self._config)

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
            builder = system.get("event.builder") if system and hasattr(system, "get") else None
            run_id = builder.run_id if builder is not None else ""
            ledger_head = builder.ledger_head() if builder is not None else None
            return {
                "run_id": run_id,
                "ledger_head": ledger_head,
                "plugins_loaded": len(getattr(system, "plugins", []) or []),
                "safe_mode": bool(self._safe_mode),
                "capture_active": bool(self._run_active),
                "paused_until_utc": self._paused_until_utc,
                "paused": bool(self._paused_until_utc),
            }

    def _start_components(self) -> None:
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
                if hasattr(component, "start"):
                    component.start()
        self._run_active = True

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
        self._start_components()
        return {"ok": True, "running": True}

    def run_stop(self, *, preserve_pause: bool = False) -> dict[str, Any]:
        if not preserve_pause:
            with self._pause_lock:
                self._clear_pause_locked()
        self._stop_components()
        return {"ok": True, "running": False}

    def run_pause(self, minutes: float) -> dict[str, Any]:
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
            return {"stats": stats}

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

    def telemetry(self) -> dict[str, Any]:
        return telemetry_snapshot()

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
) -> UXFacade:
    return UXFacade(
        paths=default_config_paths(),
        safe_mode=safe_mode,
        persistent=persistent,
        start_conductor=start_conductor,
    )
