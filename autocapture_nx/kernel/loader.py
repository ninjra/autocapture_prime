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
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.ids import ensure_run_id
from autocapture_nx.plugin_system.registry import PluginRegistry

from .system import System


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str


class Kernel:
    def __init__(self, config_paths: ConfigPaths, safe_mode: bool = False) -> None:
        self.config_paths = config_paths
        self.safe_mode = safe_mode
        self.config: dict[str, Any] = {}
        self.system: System | None = None

    def boot(self) -> System:
        self.config = load_config(self.config_paths, safe_mode=self.safe_mode)
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
        self._record_run_start(builder)
        self.system = System(config=self.config, plugins=plugins, capabilities=capabilities)
        return self.system

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
        builder = self.system.get("event.builder")
        builder.ledger_entry("system", inputs=[], outputs=[], payload={"event": "system.stop"})
        self._write_run_state(builder.run_id, "stopped")

    def _run_state_path(self) -> Path:
        data_dir = self.config.get("storage", {}).get("data_dir", "data")
        return Path(data_dir) / "run_state.json"

    def _write_run_state(self, run_id: str, state: str) -> None:
        path = self._run_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": run_id, "state": state, "ts_utc": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def _record_run_start(self, builder: EventBuilder) -> None:
        path = self._run_state_path()
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                if previous.get("state") == "running":
                    builder.ledger_entry(
                        "system",
                        inputs=[],
                        outputs=[],
                        payload={"event": "system.crash", "previous_run_id": previous.get("run_id")},
                    )
            except Exception:
                pass
        builder.ledger_entry("system", inputs=[], outputs=[], payload={"event": "system.start"})
        self._write_run_state(builder.run_id, "running")

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
                manifest_paths = registry.discover_manifests()
                manifests_by_id: dict[str, Path] = {}
                for manifest_path in manifest_paths:
                    with manifest_path.open("r", encoding="utf-8") as handle:
                        manifest = json.load(handle)
                    manifests_by_id[manifest.get("plugin_id", "")] = manifest_path
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
