"""Kernel bootstrap and health checks."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def boot(self) -> System:
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
        self.system = System(config=self.config, plugins=plugins, capabilities=capabilities)
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
        manifest = {
            "record_type": "system.run_manifest",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "config": {
                "schema_hash": effective.schema_hash if effective else None,
                "effective_hash": effective.effective_hash if effective else None,
            },
            "locks": lock_hashes,
            "plugins": sorted({p.plugin_id for p in plugins}),
            "storage": {
                "data_dir": self.config.get("storage", {}).get("data_dir", "data"),
                "fsync_policy": self.config.get("storage", {}).get("fsync_policy", "none"),
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
        supported_backends = {"mss"}
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
