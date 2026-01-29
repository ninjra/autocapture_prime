"""NX UX facade shared by CLI and Web console."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
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

    def config_get(self) -> dict[str, Any]:
        return dict(self._config)

    def config_set(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("config_patch_invalid")
        user_cfg = {}
        if self._paths.user_path.exists():
            user_cfg = json.loads(self._paths.user_path.read_text(encoding="utf-8"))
        merged = _deep_merge(user_cfg, patch)
        validate_config(self._paths.schema_path, _deep_merge(self._config, patch))
        self._paths.user_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.user_path.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
        return self.reload_config()

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
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        manager.settings_set(plugin_id, patch)
        self.reload_config()
        return manager.settings_get(plugin_id)

    def plugins_enable(self, plugin_id: str) -> None:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        manager.enable(plugin_id)
        self.reload_config()

    def plugins_disable(self, plugin_id: str) -> None:
        manager = PluginManager(self._config, safe_mode=self._safe_mode)
        manager.disable(plugin_id)
        self.reload_config()

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
            }

    def run_start(self) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            capture = system.get("capture.source") if system and hasattr(system, "get") else None
            audio = system.get("capture.audio") if system and hasattr(system, "get") else None
            input_tracker = system.get("tracking.input") if system and hasattr(system, "get") else None
            window_meta = system.get("window.metadata") if system and hasattr(system, "get") else None
            cursor_tracker = system.get("tracking.cursor") if system and hasattr(system, "has") and system.has("tracking.cursor") else None
            clipboard = system.get("tracking.clipboard") if system and hasattr(system, "has") and system.has("tracking.clipboard") else None
            file_activity = system.get("tracking.file_activity") if system and hasattr(system, "has") and system.has("tracking.file_activity") else None
            for component in (capture, audio, input_tracker, window_meta, cursor_tracker, clipboard, file_activity):
                if component is None:
                    continue
                if hasattr(component, "start"):
                    component.start()
            self._run_active = True
            return {"ok": True, "running": True}

    def run_stop(self) -> dict[str, Any]:
        with self._kernel_mgr.session() as system:
            capture = system.get("capture.source") if system and hasattr(system, "get") else None
            audio = system.get("capture.audio") if system and hasattr(system, "get") else None
            input_tracker = system.get("tracking.input") if system and hasattr(system, "get") else None
            window_meta = system.get("window.metadata") if system and hasattr(system, "get") else None
            cursor_tracker = system.get("tracking.cursor") if system and hasattr(system, "has") and system.has("tracking.cursor") else None
            clipboard = system.get("tracking.clipboard") if system and hasattr(system, "has") and system.has("tracking.clipboard") else None
            file_activity = system.get("tracking.file_activity") if system and hasattr(system, "has") and system.has("tracking.file_activity") else None
            for component in (capture, audio, input_tracker, window_meta, cursor_tracker, clipboard, file_activity):
                if component is None:
                    continue
                if hasattr(component, "stop"):
                    component.stop()
            self._run_active = False
            return {"ok": True, "running": False}

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
