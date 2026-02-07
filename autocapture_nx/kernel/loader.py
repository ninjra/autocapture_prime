"""Kernel bootstrap and health checks."""

from __future__ import annotations

import json
import hashlib
import math
import os
import platform
import getpass
import time
from importlib import metadata as importlib_metadata
from email.message import Message
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, cast

from autocapture_nx.kernel.config import ConfigPaths, load_config, validate_config
from autocapture_nx.kernel.paths import default_config_dir, resolve_repo_path
from autocapture_nx.kernel.errors import ConfigError
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file, sha256_text
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx import __version__ as kernel_version
from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.determinism import apply_runtime_determinism
from autocapture_nx.kernel.telemetry import record_telemetry
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.metadata_store import persist_unavailable_record
from autocapture_nx.kernel.atomic_write import atomic_write_json
from autocapture_nx.kernel.instance_lock import acquire_instance_lock
from autocapture_nx.plugin_system.registry import PluginRegistry
from autocapture_nx.plugin_system.runtime import global_network_deny, set_global_network_deny
from autocapture_nx.plugin_system.host import close_all_subprocess_hosts

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


@dataclass
class CrashLoopStatus:
    enabled: bool
    crash_detected: bool
    crash_count: int
    max_crashes: int
    window_s: int
    min_runtime_s: int
    cooldown_s: int
    safe_mode_until: str | None
    force_safe_mode: bool
    reason: str | None
    last_crash_ts: str | None
    previous_run_id: str | None


@dataclass(frozen=True)
class EffectiveConfig:
    data: dict[str, Any]
    schema_hash: str
    effective_hash: str


def _canonicalize_config_for_hash(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _canonicalize_config_for_hash(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonicalize_config_for_hash(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ConfigError("Config contains NaN/Inf, which is not supported.")
        if obj.is_integer():
            return int(obj)
        return {"__float__": format(obj, ".15g")}
    return obj


def _startup_profile_enabled() -> bool:
    return os.getenv("AUTOCAPTURE_STARTUP_PROFILE", "").lower() in {"1", "true", "yes"}


class StartupProfiler:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._marks: list[tuple[str, float]] = []
        self._t0 = time.perf_counter()

    def mark(self, label: str) -> None:
        if not self.enabled:
            return
        self._marks.append((label, time.perf_counter()))

    def summary(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        marks = [("start", self._t0)] + self._marks
        spans: list[dict[str, Any]] = []
        for idx in range(1, len(marks)):
            label, ts = marks[idx]
            prev_label, prev_ts = marks[idx - 1]
            spans.append(
                {
                    "label": label,
                    "from": prev_label,
                    "ms": round((ts - prev_ts) * 1000.0, 3),
                }
            )
        total_ms = round((marks[-1][1] - marks[0][1]) * 1000.0, 3) if marks else 0.0
        return {"total_ms": total_ms, "spans": spans}

    def finish(self) -> None:
        if not self.enabled:
            return
        payload = self.summary()
        if not payload:
            return
        record_telemetry("startup.profile", payload)
        try:
            print(f"startup_profile={json.dumps(payload, sort_keys=True)}")
        except Exception:
            pass


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
        os.environ.setdefault("AUTOCAPTURE_ROOT", str(resolve_repo_path(".")))
        self.config: dict[str, Any] = {}
        self.effective_config: EffectiveConfig | None = None
        self.system: System | None = None
        self.safe_mode_reason: str | None = None
        self._crash_loop_status: CrashLoopStatus | None = None
        self._run_started_at: str | None = None
        self._conductor: Any | None = None
        self._package_versions_cache: dict[str, str] | None = None
        self._network_deny_prev: bool | None = None
        self._instance_lock: Any | None = None

    def boot(self, *, start_conductor: bool = True, fast_boot: bool | None = None) -> System:
        profiler = StartupProfiler(enabled=_startup_profile_enabled())
        profiler.mark("boot.start")
        effective = self.load_effective_config()
        profiler.mark("load_effective_config")
        crash_status = self._evaluate_crash_loop(effective.data)
        self._crash_loop_status = crash_status
        if crash_status.force_safe_mode:
            if not self.safe_mode:
                self.safe_mode = True
                effective = self.load_effective_config()
                profiler.mark("load_effective_config_safe_mode")
            if not self.safe_mode_reason:
                self.safe_mode_reason = crash_status.reason or "crash_loop"
        elif self.safe_mode and not self.safe_mode_reason:
            self.safe_mode_reason = "manual"
        self.effective_config = effective
        self.config = effective.data
        ensure_run_id(self.config)
        apply_runtime_determinism(self.config)
        try:
            data_dir = self.config.get("storage", {}).get("data_dir", "data")
            self._instance_lock = acquire_instance_lock(data_dir)
        except Exception:
            # Fail closed: concurrent writers must be prevented.
            raise
        computed_fast_boot = bool(
            self.safe_mode and self.config.get("kernel", {}).get("safe_mode_fast_boot", False)
        )
        # One-shot commands (CLI query/verify/etc) should avoid heavy boot steps that
        # can fan out plugin work and destabilize WSL. Persistent runs (capture/web)
        # can still opt into full boot by passing fast_boot=False.
        fast_boot = computed_fast_boot if fast_boot is None else bool(fast_boot)
        self._verify_contract_lock()
        profiler.mark("verify_contract_lock")
        allow_kernel_net = os.getenv("AUTOCAPTURE_ALLOW_KERNEL_NETWORK", "").lower() in {"1", "true", "yes"}
        self._network_deny_prev = global_network_deny()
        set_global_network_deny(not allow_kernel_net)
        profiler.mark("network_policy")
        registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
        profiler.mark("registry_init")
        plugins, capabilities = registry.load_plugins()
        profiler.mark("load_plugins")

        updated = self._apply_meta_plugins(self.config, plugins)
        if updated != self.config:
            # Meta plugins can mutate config and require a re-load. The initial `load_plugins()`
            # may have started subprocess plugin hosts; make sure we close those instances
            # before we drop references and start the second load to avoid runaway RAM/processes.
            for plugin in list(plugins):
                instance = getattr(plugin, "instance", None)
                if instance is None:
                    continue
                for method in ("stop", "close"):
                    target = getattr(instance, method, None)
                    if callable(target):
                        try:
                            target()
                        except Exception:
                            pass
            ensure_run_id(updated)
            apply_runtime_determinism(updated)
            validate_config(self.config_paths.schema_path, updated)
            self.config = updated
            registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
            plugins, capabilities = registry.load_plugins()
            profiler.mark("load_plugins_meta")

        builder = EventBuilder(
            self.config,
            capabilities.get("journal.writer"),
            capabilities.get("ledger.writer"),
            capabilities.get("anchor.writer"),
        )
        capabilities.register("event.builder", builder, network_allowed=False)
        profiler.mark("event_builder")
        try:
            from autocapture.runtime.governor import RuntimeGovernor
            from autocapture.runtime.scheduler import Scheduler

            governor = capabilities.all().get("runtime.governor")
            if governor is None:
                governor = RuntimeGovernor()
                try:
                    governor.update_config(self.config)
                except Exception:
                    pass
                capabilities.register("runtime.governor", governor, network_allowed=False)
            scheduler = capabilities.all().get("runtime.scheduler")
            if scheduler is None:
                try:
                    scheduler = Scheduler(governor)
                except Exception:
                    scheduler = Scheduler(RuntimeGovernor())
                capabilities.register("runtime.scheduler", scheduler, network_allowed=False)
        except Exception:
            pass
        try:
            from autocapture_nx.kernel.egress_approvals import EgressApprovalStore

            approval_store = EgressApprovalStore(self.config, builder)
            capabilities.register("egress.approval_store", approval_store, network_allowed=False)
        except Exception:
            pass
        profiler.mark("egress_store")
        if not fast_boot:
            self._record_storage_manifest(
                builder,
                capabilities,
                plugins,
                include_packages=True,
                include_counts=True,
            )
        profiler.mark("record_storage_manifest")
        self._record_run_start(builder)
        profiler.mark("record_run_start")
        if not fast_boot:
            self._run_recovery(builder, capabilities)
        profiler.mark("run_recovery")
        if not fast_boot:
            self._run_integrity_sweep(builder, capabilities)
        profiler.mark("integrity_sweep")
        self.system = System(config=self.config, plugins=plugins, capabilities=capabilities)
        if start_conductor and not fast_boot:
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
        profiler.mark("conductor")
        profiler.finish()
        return self.system

    def reload_plugins(self, plugin_ids: list[str] | None = None) -> dict[str, Any]:
        if self.system is None:
            raise RuntimeError("kernel_not_running")
        registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
        plugins, capabilities, report = registry.hot_reload(self.system.plugins, plugin_ids=plugin_ids)
        if self.system.has("event.builder"):
            builder = self.system.get("event.builder")
            capabilities.register("event.builder", builder, network_allowed=False)
        if self.system.has("egress.approval_store"):
            store = self.system.get("egress.approval_store")
            capabilities.register("egress.approval_store", store, network_allowed=False)
        if self.system.has("runtime.conductor"):
            conductor = self.system.get("runtime.conductor")
            capabilities.register("runtime.conductor", conductor, network_allowed=False)
        self.system.plugins = plugins
        self.system.capabilities = capabilities
        return {"ok": True, **report}

    def load_effective_config(self) -> EffectiveConfig:
        cfg = load_config(self.config_paths, safe_mode=self.safe_mode)
        schema_hash = sha256_file(self.config_paths.schema_path)
        effective_hash = sha256_text(dumps(_canonicalize_config_for_hash(cfg)))
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

    def _dep_lock_hash(self) -> tuple[str | None, str | None]:
        lock_path = resolve_repo_path("requirements.lock.json")
        if not lock_path.exists():
            return None, None
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        expected = lock.get("content_hash")
        try:
            import tomllib
        except Exception:
            return expected, None
        pyproject = resolve_repo_path("pyproject.toml")
        if not pyproject.exists():
            return expected, None
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        deps = sorted(project.get("dependencies", []) or [])
        optional = project.get("optional-dependencies", {}) or {}
        optional_sorted = {key: sorted(value or []) for key, value in sorted(optional.items())}
        payload = {
            "version": 1,
            "python": project.get("requires-python"),
            "dependencies": deps,
            "optional_dependencies": optional_sorted,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return expected, actual

    def _parse_requirement(self, requirement: str) -> tuple[str, str | None]:
        text = requirement.strip()
        if not text:
            return "", None
        name = text.split(";")[0].strip()
        if "[" in name:
            name = name.split("[", 1)[0].strip()
        for op in (">=", "<=", "==", ">", "<"):
            if op in text:
                parts = text.split(op, 1)
                return parts[0].split("[", 1)[0].strip(), f"{op}{parts[1].strip()}"
        return name, None

    def _version_tuple(self, version: str) -> tuple[int, ...]:
        parts = []
        for part in version.strip().lstrip("v").split("."):
            if part.isdigit():
                parts.append(int(part))
            else:
                num = ""
                for ch in part:
                    if ch.isdigit():
                        num += ch
                    else:
                        break
                if num:
                    parts.append(int(num))
        return tuple(parts)

    def _version_satisfies(self, current: str, requirement: str) -> bool:
        ops = (">=", "<=", ">", "<", "==")
        op = "=="
        target = requirement.strip()
        for candidate in ops:
            if target.startswith(candidate):
                op = candidate
                target = target[len(candidate) :].strip()
                break
        current_v = self._version_tuple(current)
        target_v = self._version_tuple(target)
        if op == ">=":
            return current_v >= target_v
        if op == "<=":
            return current_v <= target_v
        if op == ">":
            return current_v > target_v
        if op == "<":
            return current_v < target_v
        return current_v == target_v

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
        try:
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
                locks=self._lock_hashes(),
                config_hash=self.effective_config.effective_hash if self.effective_config else None,
                safe_mode=self.safe_mode,
                safe_mode_reason=self.safe_mode_reason,
            )
            if self._network_deny_prev is not None:
                set_global_network_deny(self._network_deny_prev)
                self._network_deny_prev = None
        finally:
            # Ensure subprocess plugin hosts and other plugin resources are released.
            try:
                self.system.close()
            except Exception:
                pass
            try:
                if self._instance_lock is not None:
                    self._instance_lock.close()
            except Exception:
                pass
            self._instance_lock = None
            try:
                # Best-effort cleanup: prevents host_runner buildup when repeated
                # CLI sessions/tests create kernels without a long-lived daemon.
                close_all_subprocess_hosts(reason="kernel_shutdown")
            except Exception:
                pass
            self.system = None
            self._conductor = None

    def _run_state_path(self) -> Path:
        return self._run_state_path_for_config(self.config)

    def _run_state_path_for_config(self, config: dict[str, Any]) -> Path:
        data_dir = config.get("storage", {}).get("data_dir", "data")
        return Path(data_dir) / "run_state.json"

    def _load_run_state(self) -> dict[str, Any] | None:
        path = self._run_state_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load_run_state_for_config(self, config: dict[str, Any]) -> dict[str, Any] | None:
        path = self._run_state_path_for_config(config)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _crash_history_path(self, config: dict[str, Any]) -> Path:
        data_dir = config.get("storage", {}).get("data_dir", "data")
        return Path(data_dir) / "crash_history.json"

    def _load_crash_history(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"events": [], "safe_mode_until": None, "last_clean_utc": None}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"events": [], "safe_mode_until": None, "last_clean_utc": None}
        events = payload.get("events")
        if not isinstance(events, list):
            events = []
        cleaned = [event for event in events if isinstance(event, dict)]
        safe_mode_until = payload.get("safe_mode_until") if payload.get("safe_mode_until") else None
        last_clean = payload.get("last_clean_utc") if payload.get("last_clean_utc") else None
        return {"events": cleaned, "safe_mode_until": safe_mode_until, "last_clean_utc": last_clean}

    def _write_crash_history(self, path: Path, history: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "events": list(history.get("events", [])),
            "safe_mode_until": history.get("safe_mode_until"),
            "last_clean_utc": history.get("last_clean_utc"),
        }
        atomic_write_json(path, payload, sort_keys=True, indent=None)

    def _crash_loop_policy(self, config: dict[str, Any]) -> dict[str, Any]:
        kernel_cfg = config.get("kernel", {}) if isinstance(config, dict) else {}
        crash_cfg = kernel_cfg.get("crash_loop", {}) if isinstance(kernel_cfg, dict) else {}
        return {
            "enabled": bool(crash_cfg.get("enabled", True)),
            "max_crashes": int(crash_cfg.get("max_crashes", 3)),
            "window_s": int(crash_cfg.get("window_s", 600)),
            "min_runtime_s": int(crash_cfg.get("min_runtime_s", 0)),
            "cooldown_s": int(crash_cfg.get("cooldown_s", 0)),
            "reset_on_clean_shutdown": bool(crash_cfg.get("reset_on_clean_shutdown", True)),
        }

    def _evaluate_crash_loop(self, config: dict[str, Any]) -> CrashLoopStatus:
        policy = self._crash_loop_policy(config)
        status = CrashLoopStatus(
            enabled=bool(policy["enabled"]),
            crash_detected=False,
            crash_count=0,
            max_crashes=int(policy["max_crashes"]),
            window_s=int(policy["window_s"]),
            min_runtime_s=int(policy["min_runtime_s"]),
            cooldown_s=int(policy["cooldown_s"]),
            safe_mode_until=None,
            force_safe_mode=False,
            reason=None,
            last_crash_ts=None,
            previous_run_id=None,
        )
        if not status.enabled:
            return status
        now = datetime.now(timezone.utc)
        run_state = self._load_run_state_for_config(config)
        history_path = self._crash_history_path(config)
        history = self._load_crash_history(history_path)
        events: list[dict[str, Any]] = list(history.get("events", []))
        write_history = False

        if isinstance(run_state, dict) and run_state.get("state") == "stopped" and policy["reset_on_clean_shutdown"]:
            events = []
            history["safe_mode_until"] = None
            history["last_clean_utc"] = now.isoformat()
            write_history = True

        if isinstance(run_state, dict) and run_state.get("state") == "running":
            status.crash_detected = True
            status.previous_run_id = run_state.get("run_id")
            started_at = run_state.get("started_at") or run_state.get("ts_utc")
            start_dt = self._parse_ts(started_at)
            runtime_s = 0
            if start_dt is not None:
                runtime_s = max(0, int((now - start_dt).total_seconds()))
            if runtime_s >= status.min_runtime_s:
                events.append(
                    {
                        "ts_utc": now.isoformat(),
                        "run_id": run_state.get("run_id"),
                        "runtime_s": runtime_s,
                    }
                )
                write_history = True

        window_start = now - timedelta(seconds=max(0, status.window_s))
        filtered: list[dict[str, Any]] = []
        for event in events:
            ts = self._parse_ts(event.get("ts_utc"))
            if ts is None or ts < window_start:
                continue
            filtered.append(event)
        if filtered != events:
            write_history = True
        history["events"] = filtered
        status.crash_count = len(filtered)
        if filtered:
            last_event = filtered[-1]
            status.last_crash_ts = last_event.get("ts_utc")

        safe_mode_until = history.get("safe_mode_until")
        if safe_mode_until:
            until_dt = self._parse_ts(safe_mode_until)
            if until_dt is not None and until_dt > now:
                status.force_safe_mode = True
                status.reason = "crash_loop"
            else:
                history["safe_mode_until"] = None
                write_history = True

        if status.crash_count >= status.max_crashes:
            status.force_safe_mode = True
            status.reason = "crash_loop"
            if status.cooldown_s > 0:
                history["safe_mode_until"] = (now + timedelta(seconds=status.cooldown_s)).isoformat()
            else:
                history["safe_mode_until"] = None
            write_history = True

        status.safe_mode_until = history.get("safe_mode_until")
        if write_history:
            self._write_crash_history(history_path, history)
        return status

    def crash_loop_status(self) -> dict[str, Any] | None:
        if self._crash_loop_status is None:
            return None
        return asdict(self._crash_loop_status)

    def _write_run_state(
        self,
        run_id: str,
        state: str,
        *,
        started_at: str | None = None,
        stopped_at: str | None = None,
        ledger_head: str | None = None,
        locks: dict[str, str | None] | None = None,
        config_hash: str | None = None,
        safe_mode: bool | None = None,
        safe_mode_reason: str | None = None,
    ) -> None:
        path = self._run_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "run_id": run_id,
            "state": state,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        if started_at:
            payload["started_at"] = started_at
        if stopped_at:
            payload["stopped_at"] = stopped_at
        if ledger_head:
            payload["ledger_head"] = ledger_head
        if locks is not None:
            payload["locks"] = locks
        if config_hash:
            payload["config_hash"] = config_hash
        if safe_mode is not None:
            payload["safe_mode"] = bool(safe_mode)
        if safe_mode_reason:
            payload["safe_mode_reason"] = safe_mode_reason
        atomic_write_json(path, payload, sort_keys=True, indent=None)

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
            crash_loop = self.crash_loop_status()
            if crash_loop is not None:
                crash_payload["crash_loop"] = crash_loop
            builder.ledger_entry("system", inputs=[], outputs=[], payload=crash_payload)
        lock_hashes = self._lock_hashes()
        effective = self.effective_config
        actor = getpass.getuser()
        if isinstance(previous, dict):
            prev_locks = previous.get("locks")
            if isinstance(prev_locks, dict) and prev_locks and prev_locks != lock_hashes:
                builder.ledger_entry(
                    "security",
                    inputs=[value for value in prev_locks.values() if value is not None],
                    outputs=[value for value in lock_hashes.values() if value is not None],
                    payload={
                        "event": "lock_update",
                        "actor": actor,
                        "previous": prev_locks,
                        "current": lock_hashes,
                    },
                )
            prev_config = previous.get("config_hash")
            curr_config = effective.effective_hash if effective else None
            if prev_config and curr_config and prev_config != curr_config:
                builder.ledger_entry(
                    "security",
                    inputs=[str(prev_config)],
                    outputs=[str(curr_config)],
                    payload={
                        "event": "config_change",
                        "actor": actor,
                        "previous": prev_config,
                        "current": curr_config,
                    },
                )
        start_ts = datetime.now(timezone.utc).isoformat()
        self._run_started_at = start_ts
        payload: dict[str, Any] = {
            "event": "system.start",
            "run_id": builder.run_id,
            "kernel_version": kernel_version,
            "config": {
                "schema_hash": effective.schema_hash if effective else None,
                "effective_hash": effective.effective_hash if effective else None,
            },
            "locks": lock_hashes,
        }
        payload["safe_mode"] = bool(self.safe_mode)
        if self.safe_mode_reason:
            payload["safe_mode_reason"] = self.safe_mode_reason
        crash_loop = self.crash_loop_status()
        if crash_loop is not None:
            payload["crash_loop"] = crash_loop
        builder.ledger_entry("system", inputs=[], outputs=[], payload=payload, ts_utc=start_ts)
        self._write_run_state(
            builder.run_id,
            "running",
            started_at=start_ts,
            locks=lock_hashes,
            config_hash=effective.effective_hash if effective else None,
            safe_mode=self.safe_mode,
            safe_mode_reason=self.safe_mode_reason,
        )

    def _record_storage_manifest(
        self,
        builder: EventBuilder,
        capabilities,
        plugins: list,
        *,
        include_packages: bool = True,
        include_counts: bool = True,
    ) -> None:
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
        packages = self._package_versions() if include_packages else {}
        counts = self._store_counts(metadata, media) if include_counts else None
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
            for file_path in sorted(root_path.rglob("*.tmp")):
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
                record_ids = list(metadata.keys())
                for record_id in sorted(record_ids):
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

            for record_id in sorted(segment_records):
                record = segment_records[record_id]
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
        self._reconcile_capture_journal(builder, capabilities)

    def _reconcile_capture_journal(self, builder: EventBuilder, capabilities: Any | None = None) -> None:
        if capabilities is None:
            return
        data_dir = self.config.get("storage", {}).get("data_dir", "data")
        journal_path = Path(data_dir) / "journal.ndjson"
        if not journal_path.exists():
            return
        try:
            metadata = capabilities.get("storage.metadata")
        except Exception:
            metadata = None
        try:
            media = capabilities.get("storage.media")
        except Exception:
            media = None
        if metadata is None or media is None:
            return
        stage_events: dict[str, dict[str, Any]] = {}
        committed: set[str] = set()
        try:
            for line in journal_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                event_type = entry.get("event_type")
                payload = entry.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                record_id = payload.get("record_id")
                if not record_id:
                    continue
                if event_type == "capture.stage":
                    stage_events[str(record_id)] = {
                        "payload": payload,
                        "ts_utc": entry.get("ts_utc"),
                    }
                elif event_type == "capture.commit":
                    committed.add(str(record_id))
        except Exception:
            return

        def _media_exists(store: Any, record_id: str) -> bool:
            if store is None:
                return False
            if hasattr(store, "exists"):
                try:
                    return bool(store.exists(record_id))
                except Exception:
                    return False
            if hasattr(store, "keys"):
                try:
                    return record_id in set(store.keys())
                except Exception:
                    return False
            try:
                return store.get(record_id) is not None
            except Exception:
                return False

        recovered: list[str] = []
        unavailable: list[str] = []
        for record_id, info in stage_events.items():
            if record_id in committed:
                continue
            payload = info.get("payload", {}) if isinstance(info, dict) else {}
            record_type = str(payload.get("record_type") or "")
            ts_utc = str(info.get("ts_utc") or datetime.now(timezone.utc).isoformat())
            meta_record = None
            try:
                meta_record = metadata.get(record_id, None)
            except Exception:
                meta_record = None
            meta_payload = meta_record if isinstance(meta_record, dict) else {}
            has_meta = bool(meta_payload.get("record_type"))
            has_media = _media_exists(media, record_id)
            if has_meta and has_media:
                meta_payload = cast(dict[str, Any], meta_record)
                commit_payload = {
                    "record_id": record_id,
                    "record_type": record_type or meta_payload.get("record_type"),
                    "reconciled": True,
                    "content_hash": meta_payload.get("content_hash"),
                    "payload_hash": meta_payload.get("payload_hash"),
                }
                try:
                    commit_record_type = str(commit_payload.get("record_type") or "evidence.capture.segment")
                    builder.capture_commit(
                        record_id,
                        commit_record_type,
                        ts_utc=ts_utc,
                        payload=commit_payload,
                    )
                    builder.ledger_entry(
                        "capture.reconcile",
                        inputs=[record_id],
                        outputs=[],
                        payload={"event": "capture.reconcile", **commit_payload},
                        ts_utc=ts_utc,
                    )
                except Exception:
                    pass
                recovered.append(record_id)
                continue
            reason = "missing_media" if not has_media else "missing_metadata"
            try:
                unavailable_id = persist_unavailable_record(
                    metadata,
                    builder.run_id,
                    ts_utc=ts_utc,
                    reason=reason,
                    parent_evidence_id=record_id,
                    source_record_type=record_type or None,
                    details={"event": "capture.unavailable"},
                )
                builder.capture_unavailable(
                    record_id,
                    record_type or "evidence.capture.unknown",
                    reason,
                    ts_utc=ts_utc,
                    payload={"unavailable_id": unavailable_id},
                )
                builder.ledger_entry(
                    "capture.unavailable",
                    inputs=[record_id],
                    outputs=[unavailable_id],
                    payload={
                        "event": "capture.unavailable",
                        "record_id": record_id,
                        "record_type": record_type,
                        "reason": reason,
                        "unavailable_id": unavailable_id,
                    },
                    ts_utc=ts_utc,
                )
            except Exception:
                pass
            unavailable.append(record_id)

        if recovered or unavailable:
            summary = {
                "event": "capture.reconcile",
                "recovered_count": int(len(recovered)),
                "unavailable_count": int(len(unavailable)),
            }
            if recovered:
                summary["recovered_samples"] = recovered[:5]
            if unavailable:
                summary["unavailable_samples"] = unavailable[:5]
            ts_utc = datetime.now(timezone.utc).isoformat()
            try:
                builder.journal_event("capture.reconcile", summary, ts_utc=ts_utc)
                builder.ledger_entry("capture.reconcile.summary", inputs=[], outputs=[], payload=summary, ts_utc=ts_utc)
            except Exception:
                pass

    def _run_integrity_sweep(self, builder: EventBuilder, capabilities: Any | None = None) -> None:
        if capabilities is None:
            return
        try:
            metadata = capabilities.get("storage.metadata")
        except Exception:
            metadata = None
        try:
            media = capabilities.get("storage.media")
        except Exception:
            media = None
        stale: dict[str, str] = {}
        if metadata is None or media is None:
            try:
                capabilities.register("integrity.stale", stale, network_allowed=False)
            except Exception:
                pass
            return
        from autocapture.pillars.citable import verify_evidence

        try:
            _ok, errors = verify_evidence(metadata, media)
        except Exception:
            errors = []
        existing_unavailable: dict[str, str] = {}
        try:
            for key in metadata.keys():
                record = metadata.get(key, {})
                if not isinstance(record, dict):
                    continue
                if record.get("record_type") != "evidence.capture.unavailable":
                    continue
                parent = record.get("parent_evidence_id")
                if parent:
                    existing_unavailable[str(parent)] = str(record.get("reason") or "unavailable")
        except Exception:
            existing_unavailable = {}
        reason_map = {
            "evidence_missing": "missing_media",
            "content_hash_mismatch": "content_hash_mismatch",
            "payload_hash_mismatch": "payload_hash_mismatch",
        }
        now = datetime.now(timezone.utc).isoformat()
        for error in errors:
            if not isinstance(error, str) or ":" not in error:
                continue
            kind, record_id = error.split(":", 1)
            if kind not in reason_map:
                continue
            record_id = str(record_id)
            if record_id in stale:
                continue
            reason = reason_map[kind]
            if record_id in existing_unavailable:
                stale[record_id] = existing_unavailable[record_id] or reason
                continue
            try:
                record = metadata.get(record_id, {})
            except Exception:
                record = {}
            record_type = str(record.get("record_type") or "")
            if not record_type.startswith("evidence.capture."):
                continue
            ts_utc = (
                record.get("ts_end_utc")
                or record.get("ts_start_utc")
                or record.get("ts_utc")
                or now
            )
            unavailable_id = None
            try:
                unavailable_id = persist_unavailable_record(
                    metadata,
                    builder.run_id,
                    ts_utc=str(ts_utc),
                    reason=reason,
                    parent_evidence_id=record_id,
                    source_record_type=record_type or None,
                    details={"event": "integrity.sweep", "kind": kind},
                )
            except Exception:
                unavailable_id = None
            payload = {
                "event": "integrity.sweep",
                "record_id": record_id,
                "record_type": record_type,
                "reason": reason,
                "kind": kind,
                "unavailable_id": unavailable_id,
            }
            try:
                builder.journal_event("integrity.sweep", payload, ts_utc=str(ts_utc))
                builder.ledger_entry(
                    "integrity.sweep",
                    inputs=[record_id],
                    outputs=[unavailable_id] if unavailable_id else [],
                    payload=payload,
                    ts_utc=str(ts_utc),
                )
            except Exception:
                pass
            stale[record_id] = reason
        if stale:
            summary = {
                "event": "integrity.sweep.summary",
                "stale_count": int(len(stale)),
                "stale_samples": list(stale.keys())[:5],
            }
            try:
                builder.journal_event("integrity.sweep.summary", summary, ts_utc=now)
                builder.ledger_entry(
                    "integrity.sweep.summary",
                    inputs=list(stale.keys())[:50],
                    outputs=[],
                    payload=summary,
                    ts_utc=now,
                )
            except Exception:
                pass
        try:
            capabilities.register("integrity.stale", stale, network_allowed=False)
        except Exception:
            pass

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

        # Instance lock should be held for the duration of the kernel process.
        checks.append(
            DoctorCheck(
                name="instance_lock",
                ok=self._instance_lock is not None,
                detail="ok" if self._instance_lock is not None else "not held",
            )
        )

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

        # Crash/power-loss hardening: state JSON must always be parseable.
        for name, path in (("run_state_json", self._run_state_path()), ("crash_history_json", self._crash_history_path(config))):
            if not path.exists():
                checks.append(DoctorCheck(name=f"{name}_present", ok=True, detail="missing"))
                continue
            try:
                json.loads(path.read_text(encoding="utf-8"))
                checks.append(DoctorCheck(name=f"{name}_valid", ok=True, detail="ok"))
            except Exception as exc:
                checks.append(DoctorCheck(name=f"{name}_valid", ok=False, detail=f"invalid ({type(exc).__name__})"))

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
        if self.safe_mode or config.get("plugins", {}).get("safe_mode", False):
            required_caps = config.get("kernel", {}).get("safe_mode_required_capabilities", required_caps)
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
        encryption_required = bool(config.get("storage", {}).get("encryption_required", False))
        encryption_enabled = bool(config.get("storage", {}).get("encryption_enabled", True))
        if encryption_required:
            ok = any(pid in plugin_ids for pid in ("builtin.storage.encrypted", "builtin.storage.sqlcipher"))
            checks.append(
                DoctorCheck(
                    name="encryption_required",
                    ok=ok,
                    detail="encrypted storage loaded" if ok else "encrypted storage missing",
                )
            )
        if encryption_required and not encryption_enabled:
            checks.append(
                DoctorCheck(
                    name="encryption_config_mismatch",
                    ok=False,
                    detail="encryption_required true but encryption_enabled false",
                )
            )
        if config.get("storage", {}).get("metadata_require_db", False):
            metadata = self.system.get("storage.metadata") if self.system is not None else None
            backend_obj = metadata
            if backend_obj is not None:
                try:
                    backend_obj = getattr(backend_obj, "target", backend_obj)
                    backend_obj = getattr(backend_obj, "_target", backend_obj)
                    backend_obj = getattr(backend_obj, "_store", backend_obj)
                except Exception:
                    backend_obj = metadata
            backend = type(backend_obj).__name__ if backend_obj is not None else "missing"
            ok = backend in {"SQLCipherStore", "PlainSQLiteStore", "EncryptedSQLiteStore"}
            if not ok and "builtin.storage.sqlcipher" in plugin_ids:
                ok = True
                backend = f"{backend} (remote)"
            checks.append(
                DoctorCheck(
                    name="metadata_db_required",
                    ok=ok,
                    detail="metadata db active" if ok else f"metadata backend is {backend}",
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
            _check_model_path("ocr_model", models_cfg.get("ocr_path"))
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
        dep_config = config.get("kernel", {}).get("dependency_pinning", {})
        if not isinstance(dep_config, dict):
            dep_config = {}
        dep_enforce = bool(dep_config.get("enforce", True))
        allow_missing = dep_config.get("allow_missing", [])
        allow_missing_set = {
            str(name).strip().lower()
            for name in (allow_missing if isinstance(allow_missing, list) else [])
            if str(name).strip()
        }
        if not dep_enforce:
            checks.append(
                DoctorCheck(
                    name="dependency_pinning",
                    ok=True,
                    detail="disabled",
                )
            )
        else:
            dep_lock_path = resolve_repo_path("requirements.lock.json")
            if not dep_lock_path.exists():
                checks.append(
                    DoctorCheck(
                        name="dependency_pinning",
                        ok=False,
                        detail="missing requirements.lock.json",
                    )
                )
            else:
                try:
                    lock = json.loads(dep_lock_path.read_text(encoding="utf-8"))
                    expected_hash, actual_hash = self._dep_lock_hash()
                    hash_ok = bool(expected_hash and actual_hash and expected_hash == actual_hash)
                    versions = self._package_versions()
                    dep_mismatches: list[str] = []
                    for req in lock.get("dependencies", []) or []:
                        name, spec = self._parse_requirement(str(req))
                        if not name:
                            continue
                        installed = versions.get(name.lower())
                        if installed is None:
                            if name.lower() in allow_missing_set:
                                continue
                            dep_mismatches.append(f"missing:{name}")
                            continue
                        if spec and not self._version_satisfies(installed, spec):
                            dep_mismatches.append(f"version:{name}")
                    optional = lock.get("optional_dependencies", {}) or {}
                    if isinstance(optional, dict):
                        for items in optional.values():
                            for req in items or []:
                                name, spec = self._parse_requirement(str(req))
                                if not name:
                                    continue
                                installed = versions.get(name.lower())
                                if installed is None:
                                    continue
                                if spec and not self._version_satisfies(installed, spec):
                                    dep_mismatches.append(f"version:{name}")
                    ok = hash_ok and not dep_mismatches
                    detail_parts = []
                    if not hash_ok:
                        if expected_hash is None or actual_hash is None:
                            detail_parts.append("lock_hash_unverifiable")
                        else:
                            detail_parts.append("lock_hash_mismatch")
                    if dep_mismatches:
                        detail_parts.append(", ".join(dep_mismatches[:5]))
                    detail = "ok" if ok else "; ".join(detail_parts) or "mismatch"
                    checks.append(
                        DoctorCheck(
                            name="dependency_pinning",
                            ok=ok,
                            detail=detail,
                        )
                    )
                except Exception as exc:
                    checks.append(
                        DoctorCheck(
                            name="dependency_pinning",
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
