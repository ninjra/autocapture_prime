"""Kernel bootstrap and health checks."""

from __future__ import annotations

import json
import os
import platform
from importlib import metadata as importlib_metadata
from email.message import Message
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from autocapture_nx.kernel.config import ConfigPaths, load_config, validate_config
from autocapture_nx.kernel.paths import default_config_dir, resolve_repo_path
from autocapture_nx.kernel.errors import ConfigError
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file, sha256_text
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx import __version__ as kernel_version
from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.registry import PluginRegistry

from .system import System


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class KernelBootArgs:
    safe_mode: bool
    config_default_path: str = "config/default.json"
    config_user_path: str = "config/user.json"


@dataclass(frozen=True)
class EffectiveConfig:
    data: dict[str, Any]
    schema_hash: str
    effective_hash: str


class Kernel:
    def __init__(self, args: KernelBootArgs | ConfigPaths, safe_mode: bool | None = None) -> None:
        if isinstance(args, KernelBootArgs):
            self.safe_mode = bool(args.safe_mode)
            self.config_paths = ConfigPaths(
                default_path=resolve_repo_path(args.config_default_path),
                user_path=resolve_repo_path(args.config_user_path),
                schema_path=resolve_repo_path("contracts/config_schema.json"),
                backup_dir=(default_config_dir() / "backup").resolve(),
            )
        else:
            self.config_paths = args
            self.safe_mode = bool(safe_mode)
        self.config: dict[str, Any] = {}
        self.effective_config: EffectiveConfig | None = None
        self.system: System | None = None
        self._run_started_at: str | None = None
        self._conductor: Any | None = None
        self._package_versions_cache: dict[str, str] | None = None

    def boot(self, *, start_conductor: bool = True) -> System:
        effective = self.load_effective_config()
        self.effective_config = effective
        self.config = effective.data
        ensure_run_id(self.config)
        self._verify_contract_lock()
        registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
        plugins, capabilities = registry.load_plugins()

        updated = self._apply_meta_plugins(self.config, plugins)
        if updated != self.config:
            ensure_run_id(updated)
            validate_config(self.config_paths.schema_path, updated)
            self.config = updated
            registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
            plugins, capabilities = registry.load_plugins()

        builder = EventBuilder(
            self.config,
            capabilities.get("journal.writer"),
            capabilities.get("ledger.writer"),
            capabilities.get("anchor.writer"),
        )
        capabilities.register("event.builder", builder, network_allowed=False)
        self._record_storage_manifest(builder, capabilities, plugins)
        self._record_run_start(builder)
        self._run_recovery(builder, capabilities)
        self.system = System(config=self.config, plugins=plugins, capabilities=capabilities)
        if start_conductor:
            try:
                from autocapture.runtime.conductor import create_conductor

                conductor = create_conductor(self.system)
                self._conductor = conductor
                capabilities.register("runtime.conductor", conductor, network_allowed=False)
                idle_cfg = self.config.get("processing", {}).get("idle", {})
                if bool(idle_cfg.get("auto_start", False)):
                    conductor.start()
            except Exception:
                self._conductor = None
        return self.system

    def load_effective_config(self) -> EffectiveConfig:
        cfg = load_config(self.config_paths, safe_mode=self.safe_mode)
        schema_hash = sha256_file(self.config_paths.schema_path)
        effective_hash = sha256_text(dumps(cfg))
        return EffectiveConfig(data=cfg, schema_hash=schema_hash, effective_hash=effective_hash)

    def validate_config(self, cfg: dict[str, Any]) -> None:
        validate_config(self.config_paths.schema_path, cfg)

    def _lock_hashes(self) -> dict[str, str | None]:
        contract_lock = resolve_repo_path("contracts/lock.json")
        contracts_hash = sha256_file(contract_lock) if contract_lock.exists() else None
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        lockfile_path = resolve_repo_path(locks_cfg.get("lockfile", "config/plugin_locks.json"))
        plugin_lock_hash = sha256_file(lockfile_path) if lockfile_path.exists() else None
        return {"contracts": contracts_hash, "plugins": plugin_lock_hash}

    def _package_versions(self) -> dict[str, str]:
        if self._package_versions_cache is not None:
            return dict(self._package_versions_cache)
        versions: dict[str, str] = {}
        try:
            for dist in importlib_metadata.distributions():
                metadata = cast(Message, dist.metadata)
                name = metadata.get("Name")
                if not name:
                    continue
                versions[str(name).lower()] = str(dist.version)
        except Exception:
            versions = {}
        self._package_versions_cache = dict(sorted(versions.items()))
        return dict(self._package_versions_cache)

    def _store_counts(self, metadata: Any, media: Any) -> dict[str, int | None]:
        counts: dict[str, int | None] = {"metadata": None, "media": None}
        if metadata is not None and hasattr(metadata, "count"):
            try:
                counts["metadata"] = int(metadata.count())
            except Exception:
                counts["metadata"] = None
        if media is not None and hasattr(media, "count"):
            try:
                counts["media"] = int(media.count())
            except Exception:
                counts["media"] = None
        return counts

    def _verify_contract_lock(self) -> None:
        lock_path = resolve_repo_path("contracts/lock.json")
        if not lock_path.exists():
            raise ConfigError("missing contracts/lock.json")
        lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        files = lock_data.get("files", {})
        mismatches = []
        for rel, expected in files.items():
            file_path = resolve_repo_path(rel)
            if not file_path.exists():
                mismatches.append(f"missing:{rel}")
                continue
            actual = sha256_file(file_path)
            if actual != expected:
                mismatches.append(f"hash_mismatch:{rel}")
        if mismatches:
            raise ConfigError(f"contract lock mismatch: {', '.join(mismatches[:5])}")

    def shutdown(self) -> None:
        if self.system is None:
            return
        if self._conductor is not None:
            try:
                self._conductor.stop()
            except Exception:
                pass
        builder = self.system.get("event.builder")
        ts_utc = datetime.now(timezone.utc).isoformat()
        duration_ms = self._run_duration_ms(ts_utc)
        summary = self._summarize_journal(builder.run_id)
        self._record_storage_manifest_final(builder, summary, duration_ms, ts_utc)
        payload = {
            "event": "system.stop",
            "run_id": builder.run_id,
            "duration_ms": int(duration_ms),
            "summary": summary,
            "previous_ledger_head": builder.ledger_head(),
        }
        stop_hash = builder.ledger_entry(
            "system",
            inputs=[],
            outputs=[],
            payload=payload,
            ts_utc=ts_utc,
        )
        self._write_run_state(
            builder.run_id,
            "stopped",
            started_at=self._run_started_at,
            stopped_at=ts_utc,
            ledger_head=stop_hash,
        )

    def _run_state_path(self) -> Path:
        data_dir = self.config.get("storage", {}).get("data_dir", "data")
        return Path(data_dir) / "run_state.json"

    def _load_run_state(self) -> dict[str, Any] | None:
        path = self._run_state_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_run_state(
        self,
        run_id: str,
        state: str,
        *,
        started_at: str | None = None,
        stopped_at: str | None = None,
        ledger_head: str | None = None,
    ) -> None:
        path = self._run_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": run_id, "state": state, "ts_utc": datetime.now(timezone.utc).isoformat()}
        if started_at:
            payload["started_at"] = started_at
        if stopped_at:
            payload["stopped_at"] = stopped_at
        if ledger_head:
            payload["ledger_head"] = ledger_head
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def _parse_ts(self, ts: str | None) -> datetime | None:
        if not ts:
            return None
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    def _run_duration_ms(self, now_ts: str) -> int:
        start_ts = self._run_started_at
        if not start_ts:
            state = self._load_run_state() or {}
            start_ts = state.get("started_at") or state.get("ts_utc")
        start_dt = self._parse_ts(start_ts)
        end_dt = self._parse_ts(now_ts)
        if not start_dt or not end_dt:
            return 0
        delta = end_dt - start_dt
        return max(0, int(delta.total_seconds() * 1000))

    def _summarize_journal(self, run_id: str) -> dict[str, int]:
        data_dir = self.config.get("storage", {}).get("data_dir", "data")
        path = Path(data_dir) / "journal.ndjson"
        summary = {"events": 0, "drops": 0, "errors": 0}
        if not path.exists():
            return summary
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("run_id") != run_id:
                    continue
                summary["events"] += 1
                event_type = str(entry.get("event_type", ""))
                if event_type == "capture.drop":
                    dropped = entry.get("payload", {}).get("dropped_frames", 1)
                    try:
                        summary["drops"] += int(dropped)
                    except Exception:
                        summary["drops"] += 1
                if "error" in event_type:
                    summary["errors"] += 1
        return summary

    def _record_run_start(self, builder: EventBuilder) -> None:
        previous = self._load_run_state()
        if isinstance(previous, dict) and previous.get("state") == "running":
            crash_payload = {
                "event": "system.crash_detected",
                "previous_run_id": previous.get("run_id"),
                "previous_state_ts_utc": previous.get("ts_utc"),
                "previous_ledger_head": builder.ledger_head(),
            }
            builder.ledger_entry("system", inputs=[], outputs=[], payload=crash_payload)
        start_ts = datetime.now(timezone.utc).isoformat()
        self._run_started_at = start_ts
        effective = self.effective_config
        payload = {
            "event": "system.start",
            "run_id": builder.run_id,
            "kernel_version": kernel_version,
            "config": {
                "schema_hash": effective.schema_hash if effective else None,
                "effective_hash": effective.effective_hash if effective else None,
            },
            "locks": self._lock_hashes(),
        }
        builder.ledger_entry("system", inputs=[], outputs=[], payload=payload, ts_utc=start_ts)
        self._write_run_state(builder.run_id, "running", started_at=start_ts)

    def _record_storage_manifest(self, builder: EventBuilder, capabilities, plugins: list) -> None:
        metadata = capabilities.get("storage.metadata")
        run_id = builder.run_id
        ts_utc = datetime.now(timezone.utc).isoformat()
        lock_hashes = self._lock_hashes()
        effective = self.effective_config
        plugin_ids: list[str] = []
        plugin_versions: dict[str, str] = {}
        for plugin in plugins:
            pid = getattr(plugin, "plugin_id", None) or plugin.manifest.get("plugin_id")
            if not pid:
                continue
            plugin_ids.append(pid)
            version = None
            if hasattr(plugin, "manifest"):
                version = plugin.manifest.get("version")
            if version:
                plugin_versions[pid] = str(version)
        metadata_backend = type(getattr(metadata, "_store", metadata)).__name__
        media = capabilities.get("storage.media")
        media_backend = type(media).__name__
        storage_cfg = self.config.get("storage", {})
        packages = self._package_versions()
        counts = self._store_counts(metadata, media)
        manifest = {
            "record_type": "system.run_manifest",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "kernel_version": kernel_version,
            "config": {
                "schema_hash": effective.schema_hash if effective else None,
                "effective_hash": effective.effective_hash if effective else None,
            },
            "policy_snapshot_hash": builder.policy_snapshot_hash(),
            "locks": lock_hashes,
            "plugins": sorted(set(plugin_ids)),
            "plugin_versions": plugin_versions,
            "packages": packages,
            "package_fingerprint": sha256_text(dumps(packages)) if packages else None,
            "storage": {
                "data_dir": storage_cfg.get("data_dir", "data"),
                "media_dir": storage_cfg.get("media_dir", "data/media"),
                "metadata_path": storage_cfg.get("metadata_path", "data/metadata.db"),
                "blob_dir": storage_cfg.get("blob_dir", "data/blobs"),
                "fsync_policy": storage_cfg.get("fsync_policy", "none"),
                "encryption_required": bool(storage_cfg.get("encryption_required", False)),
                "metadata_backend": metadata_backend,
                "media_backend": media_backend,
                "counts": counts,
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "python_version": platform.python_version(),
            },
        }
        record_id = prefixed_id(run_id, "system.run_manifest", 0)
        try:
            if hasattr(metadata, "put_new"):
                metadata.put_new(record_id, manifest)
            else:
                metadata.put(record_id, manifest)
        except FileExistsError:
            return
        builder.ledger_entry(
            "system",
            inputs=[],
            outputs=[record_id],
            payload={"event": "storage.manifest", "record_id": record_id},
            ts_utc=ts_utc,
        )

    def _record_storage_manifest_final(
        self,
        builder: EventBuilder,
        summary: dict[str, int],
        duration_ms: int,
        ts_utc: str,
    ) -> None:
        if self.system is None:
            return
        try:
            metadata = self.system.get("storage.metadata")
        except Exception:
            return
        try:
            media = self.system.get("storage.media")
        except Exception:
            media = None
        plugin_ids: list[str] = []
        plugin_versions: dict[str, str] = {}
        for plugin in self.system.plugins:
            pid = getattr(plugin, "plugin_id", None) or getattr(plugin, "manifest", {}).get("plugin_id")
            if not pid:
                continue
            plugin_ids.append(pid)
            version = None
            if hasattr(plugin, "manifest"):
                version = plugin.manifest.get("version")
            if version:
                plugin_versions[pid] = str(version)
        storage_cfg = self.config.get("storage", {})
        packages = self._package_versions()
        metadata_backend = type(getattr(metadata, "_store", metadata)).__name__
        media_backend = type(media).__name__ if media is not None else None
        counts = self._store_counts(metadata, media)
        manifest = {
            "record_type": "system.run_manifest.final",
            "run_id": builder.run_id,
            "ts_utc": ts_utc,
            "started_at": self._run_started_at,
            "stopped_at": ts_utc,
            "duration_ms": int(duration_ms),
            "summary": summary,
            "policy_snapshot_hash": builder.policy_snapshot_hash(),
            "locks": self._lock_hashes(),
            "plugins": sorted(set(plugin_ids)),
            "plugin_versions": plugin_versions,
            "packages": packages,
            "package_fingerprint": sha256_text(dumps(packages)) if packages else None,
            "storage": {
                "data_dir": storage_cfg.get("data_dir", "data"),
                "media_dir": storage_cfg.get("media_dir", "data/media"),
                "metadata_path": storage_cfg.get("metadata_path", "data/metadata.db"),
                "blob_dir": storage_cfg.get("blob_dir", "data/blobs"),
                "fsync_policy": storage_cfg.get("fsync_policy", "none"),
                "encryption_required": bool(storage_cfg.get("encryption_required", False)),
                "metadata_backend": metadata_backend,
                "media_backend": media_backend,
                "counts": counts,
            },
        }
        record_id = prefixed_id(builder.run_id, "system.run_manifest.final", 0)
        try:
            if hasattr(metadata, "put_new"):
                metadata.put_new(record_id, manifest)
            else:
                metadata.put(record_id, manifest)
        except FileExistsError:
            return
        builder.ledger_entry(
            "system",
            inputs=[],
            outputs=[record_id],
            payload={"event": "storage.manifest.final", "record_id": record_id},
            ts_utc=ts_utc,
        )

    def _run_recovery(self, builder: EventBuilder, capabilities: Any | None = None) -> None:
        data_dir = self.config.get("storage", {}).get("data_dir", "data")
        spool_dir = self.config.get("storage", {}).get("spool_dir", "data/spool")
        media_dir = self.config.get("storage", {}).get("media_dir", "data/media")
        blob_dir = self.config.get("storage", {}).get("blob_dir", "data/blobs")
        metadata_dir = self.config.get("storage", {}).get("metadata_dir", "data/metadata")
        candidates = {data_dir, spool_dir, media_dir, blob_dir, metadata_dir}
        removed: list[str] = []
        for root in sorted({str(Path(path)) for path in candidates if path}):
            root_path = Path(root)
            if not root_path.exists():
                continue
            for file_path in root_path.rglob("*.tmp"):
                try:
                    file_path.unlink()
                    removed.append(str(file_path))
                except Exception:
                    continue
        sealed_now: list[str] = []
        missing_media: list[str] = []
        if capabilities is not None:
            try:
                metadata = capabilities.get("storage.metadata")
            except Exception:
                metadata = None
            try:
                media = capabilities.get("storage.media")
            except Exception:
                media = None
            segment_records: dict[str, dict[str, Any]] = {}
            if metadata is not None and hasattr(metadata, "keys"):
                for record_id in metadata.keys():
                    record = metadata.get(record_id, {})
                    if not isinstance(record, dict):
                        continue
                    if record.get("record_type") == "evidence.capture.segment":
                        segment_records[record_id] = record
            media_ids: set[str] = set()
            if media is not None and hasattr(media, "keys"):
                try:
                    media_ids = set(media.keys())
                except Exception:
                    media_ids = set()

            sealed_ids: set[str] = set()
            ledger_path = Path(data_dir) / "ledger.ndjson"
            if ledger_path.exists():
                try:
                    for line in ledger_path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                        except Exception:
                            continue
                        payload = entry.get("payload", {})
                        if not isinstance(payload, dict):
                            continue
                        if payload.get("event") == "segment.sealed" and payload.get("segment_id"):
                            sealed_ids.add(str(payload.get("segment_id")))
                except Exception:
                    sealed_ids = set()

            for record_id, record in segment_records.items():
                if record_id in sealed_ids:
                    continue
                if record_id not in media_ids:
                    missing_media.append(record_id)
                    continue
                ts_utc = record.get("ts_end_utc") or record.get("ts_utc") or datetime.now(timezone.utc).isoformat()
                seal_payload = {
                    "event": "segment.sealed",
                    "segment_id": record_id,
                    "content_hash": record.get("content_hash"),
                    "payload_hash": record.get("payload_hash"),
                    "recovered": True,
                }
                builder.journal_event("segment.sealed", seal_payload, ts_utc=ts_utc)
                builder.ledger_entry(
                    "segment.seal",
                    inputs=[record_id],
                    outputs=[],
                    payload=seal_payload,
                    ts_utc=ts_utc,
                )
                sealed_now.append(record_id)

        if removed or sealed_now or missing_media:
            payload = {"event": "storage.recovery"}
            if removed:
                payload["removed_count"] = int(len(removed))
                payload["removed_samples"] = removed[:5]
            if sealed_now:
                payload["sealed_count"] = int(len(sealed_now))
                payload["sealed_samples"] = sealed_now[:5]
            if missing_media:
                payload["missing_media_count"] = int(len(missing_media))
                payload["missing_media_samples"] = missing_media[:5]
            ts_utc = datetime.now(timezone.utc).isoformat()
            builder.journal_event("storage.recovery", payload, ts_utc=ts_utc)
            builder.ledger_entry(
                "storage.recovery",
                inputs=[],
                outputs=[],
                payload=payload,
                ts_utc=ts_utc,
            )

    def _apply_meta_plugins(self, config: dict[str, Any], plugins: list) -> dict[str, Any]:
        updated = dict(config)
        allowed_configurators = set(
            config.get("plugins", {}).get("meta", {}).get("configurator_allowed", [])
        )
        allowed_policies = set(
            config.get("plugins", {}).get("meta", {}).get("policy_allowed", [])
        )
        for plugin in plugins:
            if plugin.plugin_id in allowed_configurators and "meta.configurator" in plugin.capabilities:
                updated = plugin.instance.configure(updated)
        for plugin in plugins:
            if plugin.plugin_id in allowed_policies and "meta.policy" in plugin.capabilities:
                permissions = updated.get("plugins", {}).get("permissions", {})
                updated.setdefault("plugins", {})["permissions"] = plugin.instance.apply(permissions)
        return updated

    def doctor(self) -> list[DoctorCheck]:
        if self.system is None:
            raise ConfigError("Kernel not booted")
        checks: list[DoctorCheck] = []
        config = self.system.config
        plugin_ids = {p.plugin_id for p in self.system.plugins}

        paths_cfg = config.get("paths", {})
        if isinstance(paths_cfg, dict):
            for key in ("config_dir", "data_dir"):
                path_value = paths_cfg.get(key)
                if not path_value:
                    checks.append(
                        DoctorCheck(
                            name=f"{key}_present",
                            ok=False,
                            detail="missing",
                        )
                    )
                    continue
                path = Path(path_value)
                if not path.exists():
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                    except Exception as exc:  # pragma: no cover - depends on filesystem permissions
                        checks.append(
                            DoctorCheck(
                                name=f"{key}_exists",
                                ok=False,
                                detail=f"missing ({exc})",
                            )
                        )
                        continue
                if not path.is_dir():
                    checks.append(
                        DoctorCheck(
                            name=f"{key}_is_dir",
                            ok=False,
                            detail="not a directory",
                        )
                    )
                    continue
                writable = os.access(path, os.W_OK)
                checks.append(
                    DoctorCheck(
                        name=f"{key}_writable",
                        ok=writable,
                        detail="ok" if writable else "not writable",
                    )
                )

        default_pack = set(config.get("plugins", {}).get("default_pack", []))
        if config.get("plugins", {}).get("safe_mode", False):
            ok = plugin_ids.issubset(default_pack)
            checks.append(
                DoctorCheck(
                    name="safe_mode_default_pack",
                    ok=ok,
                    detail="only default pack loaded" if ok else "non-default plugin loaded",
                )
            )
        required_caps = config.get("kernel", {}).get("required_capabilities", [])
        missing = [cap for cap in required_caps if cap not in self.system.capabilities.all()]
        checks.append(
            DoctorCheck(
                name="required_capabilities",
                ok=not missing,
                detail="ok" if not missing else f"missing: {missing}",
            )
        )
        backend = config.get("capture", {}).get("video", {}).get("backend")
        supported_backends = {"mss", "dxcam", "auto"}
        checks.append(
            DoctorCheck(
                name="capture_backend",
                ok=backend in supported_backends,
                detail="ok" if backend in supported_backends else f"unsupported: {backend}",
            )
        )
        if config.get("storage", {}).get("encryption_required", False):
            ok = any(pid in plugin_ids for pid in ("builtin.storage.encrypted", "builtin.storage.sqlcipher"))
            checks.append(
                DoctorCheck(
                    name="encryption_required",
                    ok=ok,
                    detail="encrypted storage loaded" if ok else "encrypted storage missing",
                )
            )
        def _check_model_path(label: str, value: Any) -> None:
            if not value:
                checks.append(
                    DoctorCheck(
                        name=f"{label}_path",
                        ok=True,
                        detail="not configured",
                    )
                )
                return
            path = Path(str(value))
            ok = path.exists()
            checks.append(
                DoctorCheck(
                    name=f"{label}_path",
                    ok=ok,
                    detail="ok" if ok else "missing",
                )
            )

        models_cfg = config.get("models", {})
        if isinstance(models_cfg, dict):
            _check_model_path("vlm_model", models_cfg.get("vlm_path"))
            _check_model_path("reranker_model", models_cfg.get("reranker_path"))
        indexing_cfg = config.get("indexing", {})
        if isinstance(indexing_cfg, dict):
            _check_model_path("embedder_model", indexing_cfg.get("embedder_model"))
        lock_path = resolve_repo_path("contracts/lock.json")
        if not lock_path.exists():
            checks.append(
                DoctorCheck(
                    name="contracts_lock",
                    ok=False,
                    detail="missing contracts/lock.json",
                )
            )
        else:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            files = lock_data.get("files", {})
            mismatches = []
            for rel, expected in files.items():
                file_path = resolve_repo_path(rel)
                if not file_path.exists():
                    mismatches.append(f"missing:{rel}")
                    continue
                actual = sha256_file(file_path)
                if actual != expected:
                    mismatches.append(f"hash_mismatch:{rel}")
            checks.append(
                DoctorCheck(
                    name="contracts_lock",
                    ok=len(mismatches) == 0,
                    detail="ok" if not mismatches else ", ".join(mismatches[:5]),
                )
            )
        locks_cfg = config.get("plugins", {}).get("locks", {})
        if not locks_cfg.get("enforce", True):
            checks.append(
                DoctorCheck(
                    name="plugin_locks",
                    ok=True,
                    detail="locks disabled",
                )
            )
        else:
            try:
                registry = PluginRegistry(config, safe_mode=self.safe_mode)
                lockfile = registry.load_lockfile()
                manifest_objs = registry.discover_manifests()
                manifests_by_id: dict[str, Path] = {}
                for manifest in manifest_objs:
                    manifests_by_id[manifest.plugin_id] = manifest.path
                mismatches = []
                plugins = lockfile.get("plugins", {})
                for pid in sorted(plugin_ids):
                    manifest_path = manifests_by_id.get(pid)
                    if manifest_path is None:
                        mismatches.append(f"missing_manifest:{pid}")
                        continue
                    expected = plugins.get(pid)
                    if not isinstance(expected, dict):
                        mismatches.append(f"missing_lock:{pid}")
                        continue
                    manifest_hash = sha256_file(manifest_path)
                    artifact_hash = sha256_directory(manifest_path.parent)
                    if manifest_hash != expected.get("manifest_sha256"):
                        mismatches.append(f"manifest_hash:{pid}")
                    if artifact_hash != expected.get("artifact_sha256"):
                        mismatches.append(f"artifact_hash:{pid}")
                checks.append(
                    DoctorCheck(
                        name="plugin_locks",
                        ok=len(mismatches) == 0,
                        detail="ok" if not mismatches else ", ".join(mismatches[:5]),
                    )
                )
            except Exception as exc:
                checks.append(
                    DoctorCheck(
                        name="plugin_locks",
                        ok=False,
                        detail=str(exc),
                    )
                )
        anchor_cfg = config.get("storage", {}).get("anchor", {})
        anchor_path = anchor_cfg.get("path")
        if anchor_path:
            data_dir = Path(config.get("storage", {}).get("data_dir", "data")).resolve()
            anchor_abs = Path(anchor_path).resolve()
            try:
                anchor_abs.relative_to(data_dir)
                ok = False
            except ValueError:
                ok = True
            checks.append(
                DoctorCheck(
                    name="anchor_separate_domain",
                    ok=ok,
                    detail="anchor store separate from data_dir" if ok else "anchor path within data_dir",
                )
            )
        forecast_cfg = config.get("storage", {}).get("forecast", {})
        if not isinstance(forecast_cfg, dict):
            forecast_cfg = {}
        if bool(forecast_cfg.get("enabled", True)):
            try:
                from autocapture.storage.forecast import forecast_from_journal

                data_dir = config.get("storage", {}).get("data_dir", "data")
                forecast = forecast_from_journal(str(data_dir))
                warn_days = int(forecast_cfg.get("warn_days", 14))
                if forecast.days_remaining is None:
                    checks.append(
                        DoctorCheck(
                            name="disk_forecast",
                            ok=True,
                            detail="insufficient data",
                        )
                    )
                else:
                    ok = forecast.days_remaining >= warn_days
                    detail = f"{forecast.days_remaining}d remaining"
                    if forecast.trend_bytes_per_day is not None:
                        detail += f" (trend {forecast.trend_bytes_per_day} B/day)"
                    checks.append(
                        DoctorCheck(
                            name="disk_forecast",
                            ok=ok,
                            detail=detail,
                        )
                    )
            except Exception as exc:
                checks.append(
                    DoctorCheck(
                        name="disk_forecast",
                        ok=False,
                        detail=str(exc),
                    )
                )
        allowed_network = set(
            config.get("plugins", {})
            .get("permissions", {})
            .get("network_allowed_plugin_ids", [])
        )
        if allowed_network != {"builtin.egress.gateway"}:
            checks.append(
                DoctorCheck(
                    name="network_allowlist",
                    ok=False,
                    detail="network allowlist must contain only builtin.egress.gateway",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    name="network_allowlist",
                    ok=True,
                    detail="ok",
                )
            )
        return checks


def default_config_paths() -> ConfigPaths:
    config_root = default_config_dir()
    return ConfigPaths(
        default_path=resolve_repo_path("config/default.json"),
        user_path=(config_root / "user.json").resolve(),
        schema_path=resolve_repo_path("contracts/config_schema.json"),
        backup_dir=(config_root / "backup").resolve(),
    )
