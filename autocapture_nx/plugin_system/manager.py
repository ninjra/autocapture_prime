"""NX plugin manager for discovery and policy settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
from autocapture_nx.kernel.config import SchemaLiteValidator

from .manifest import PluginManifest
from .registry import PluginRegistry
from .settings import build_plugin_settings, deep_merge


@dataclass(frozen=True)
class PluginStatus:
    plugin_id: str
    enabled: bool
    allowlisted: bool
    hash_ok: bool
    version: str
    permissions: Dict[str, Any]
    depends_on: List[str]
    conflicts_with: List[str]
    conflicts_active: List[str]
    conflicts_allowed: List[str]
    conflicts_blocked: List[str]
    conflicts_enforced: bool
    conflict_ok: bool


class PluginManager:
    def __init__(self, config: dict[str, Any], safe_mode: bool = False) -> None:
        self.config = config
        self.safe_mode = safe_mode
        self._registry = PluginRegistry(config, safe_mode=safe_mode)
        self._validator = SchemaLiteValidator()

    def _user_config_path(self) -> Path:
        config_dir = self.config.get("paths", {}).get("config_dir", "config")
        return Path(config_dir) / "user.json"

    def _load_user_config(self) -> dict[str, Any]:
        path = self._user_config_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_user_config(self, payload: dict[str, Any]) -> None:
        path = self._user_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _manifest_for(self, plugin_id: str, manifests: list[PluginManifest]) -> PluginManifest | None:
        for manifest in manifests:
            if manifest.plugin_id == plugin_id:
                return manifest
        return None

    def _validate_settings(self, manifest: PluginManifest, settings: dict[str, Any]) -> None:
        schema = manifest.settings_schema
        if isinstance(schema, dict):
            self._validator.validate(schema, settings)

    def _enabled_plugin_ids(self, manifests: list[PluginManifest]) -> set[str]:
        alias_map = self._alias_map(manifests)
        allowlist = set(self._normalize_ids(self.config.get("plugins", {}).get("allowlist", []), alias_map))
        enabled_map = self._normalize_enabled_map(self.config.get("plugins", {}).get("enabled", {}), alias_map)
        default_pack = set(self._normalize_ids(self.config.get("plugins", {}).get("default_pack", []), alias_map))
        enabled: set[str] = set()
        for manifest in manifests:
            pid = manifest.plugin_id
            if allowlist and pid not in allowlist:
                continue
            if self.safe_mode:
                if pid in default_pack:
                    enabled.add(pid)
                continue
            if pid in enabled_map:
                if enabled_map.get(pid):
                    enabled.add(pid)
            else:
                enabled.add(pid)
        return enabled

    def _alias_map(self, manifests: list[PluginManifest]) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        for manifest in manifests:
            for old_id in manifest.replaces:
                old = str(old_id).strip()
                if old and old not in alias_map:
                    alias_map[old] = manifest.plugin_id
        return alias_map

    def _normalize_ids(self, raw_ids: Any, alias_map: dict[str, str]) -> list[str]:
        if not isinstance(raw_ids, (list, tuple, set)):
            return []
        normalized: list[str] = []
        for pid in raw_ids:
            pid_str = str(pid).strip()
            if not pid_str:
                continue
            normalized.append(alias_map.get(pid_str, pid_str))
        return normalized

    def _normalize_enabled_map(self, enabled_map: Any, alias_map: dict[str, str]) -> dict[str, bool]:
        if not isinstance(enabled_map, dict):
            return {}
        normalized: dict[str, bool] = {}
        for pid, enabled in enabled_map.items():
            pid_str = str(pid).strip()
            if not pid_str:
                continue
            normalized[alias_map.get(pid_str, pid_str)] = bool(enabled)
        return normalized

    def list_plugins(self) -> list[PluginStatus]:
        manifests = self._registry.discover_manifests()
        enabled_ids = self._enabled_plugin_ids(manifests)
        alias_map = self._alias_map(manifests)
        allowlist = set(self._normalize_ids(self.config.get("plugins", {}).get("allowlist", []), alias_map))
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        lockfile = self._registry.load_lockfile() if locks_cfg.get("enforce", True) else {"plugins": {}}
        plugin_locks = lockfile.get("plugins", {})
        conflicts_cfg = self.config.get("plugins", {}).get("conflicts", {})
        conflicts_enforced = True
        allow_pairs: set[tuple[str, str]] = set()
        if isinstance(conflicts_cfg, dict):
            conflicts_enforced = bool(conflicts_cfg.get("enforce", True))
            pairs = conflicts_cfg.get("allow_pairs", [])
            if isinstance(pairs, list):
                for pair in pairs:
                    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                        continue
                    a = str(pair[0]).strip()
                    b = str(pair[1]).strip()
                    if not a or not b or a == b:
                        continue
                    if a <= b:
                        allow_pairs.add((a, b))
                    else:
                        allow_pairs.add((b, a))

        def _declared(manifest: PluginManifest) -> set[str]:
            declared = {str(pid).strip() for pid in manifest.conflicts_with + manifest.replaces if str(pid).strip()}
            declared.discard(manifest.plugin_id)
            return declared

        all_ids = {manifest.plugin_id for manifest in manifests}
        conflicts_active: dict[str, set[str]] = {pid: set() for pid in all_ids}
        conflicts_allowed: dict[str, set[str]] = {pid: set() for pid in all_ids}
        conflicts_blocked: dict[str, set[str]] = {pid: set() for pid in all_ids}
        declared_by_id: dict[str, set[str]] = {manifest.plugin_id: _declared(manifest) for manifest in manifests}

        for plugin_id in sorted(enabled_ids):
            declared = declared_by_id.get(plugin_id, set())
            for other in sorted(declared):
                if other not in enabled_ids:
                    continue
                pair = (plugin_id, other) if plugin_id <= other else (other, plugin_id)
                conflicts_active[plugin_id].add(other)
                conflicts_active[other].add(plugin_id)
                if pair in allow_pairs:
                    conflicts_allowed[plugin_id].add(other)
                    conflicts_allowed[other].add(plugin_id)
                else:
                    conflicts_blocked[plugin_id].add(other)
                    conflicts_blocked[other].add(plugin_id)

        rows: list[PluginStatus] = []
        for manifest in manifests:
            lock = plugin_locks.get(manifest.plugin_id, {})
            hash_ok = True
            if locks_cfg.get("enforce", True):
                manifest_hash = sha256_file(manifest.path)
                artifact_hash = sha256_directory(manifest.path.parent)
                hash_ok = (
                    manifest_hash == lock.get("manifest_sha256")
                    and artifact_hash == lock.get("artifact_sha256")
                )
            rows.append(
                PluginStatus(
                    plugin_id=manifest.plugin_id,
                    enabled=manifest.plugin_id in enabled_ids,
                    allowlisted=manifest.plugin_id in allowlist,
                    hash_ok=hash_ok,
                    version=manifest.version,
                    permissions={
                        "filesystem": manifest.permissions.filesystem,
                        "gpu": manifest.permissions.gpu,
                        "raw_input": manifest.permissions.raw_input,
                        "network": manifest.permissions.network,
                    },
                    depends_on=list(manifest.depends_on),
                    conflicts_with=sorted(declared_by_id.get(manifest.plugin_id, set())),
                    conflicts_active=sorted(conflicts_active.get(manifest.plugin_id, set())),
                    conflicts_allowed=sorted(conflicts_allowed.get(manifest.plugin_id, set())),
                    conflicts_blocked=sorted(conflicts_blocked.get(manifest.plugin_id, set())),
                    conflicts_enforced=conflicts_enforced,
                    conflict_ok=(not conflicts_blocked.get(manifest.plugin_id) or not conflicts_enforced),
                )
            )
        return sorted(rows, key=lambda r: r.plugin_id)

    def enable(self, plugin_id: str) -> None:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        enabled_map = plugins_cfg.setdefault("enabled", {})
        enabled_map[plugin_id] = True
        self._write_user_config(user_cfg)

    def disable(self, plugin_id: str) -> None:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        enabled_map = plugins_cfg.setdefault("enabled", {})
        enabled_map[plugin_id] = False
        self._write_user_config(user_cfg)

    def approve_hashes(self) -> Dict[str, Any]:
        from tools.hypervisor.scripts.update_plugin_locks import update_plugin_locks

        return update_plugin_locks()

    def settings_get(self, plugin_id: str) -> dict[str, Any]:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        manifest = self._manifest_for(plugin_id, manifests)
        if manifest is None:
            raise KeyError(f"unknown plugin {plugin_id}")
        overrides = self.config.get("plugins", {}).get("settings", {})
        override_settings = overrides.get(plugin_id, {}) if isinstance(overrides, dict) else {}
        return build_plugin_settings(
            self.config,
            settings_paths=manifest.settings_paths,
            default_settings=manifest.default_settings if isinstance(manifest.default_settings, dict) else None,
            overrides=override_settings if isinstance(override_settings, dict) else None,
        )

    def settings_set(self, plugin_id: str, patch: dict[str, Any]) -> None:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        manifest = self._manifest_for(plugin_id, manifests)
        if manifest is None:
            raise KeyError(f"unknown plugin {plugin_id}")
        if not isinstance(patch, dict):
            raise ValueError("settings_patch_invalid")
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        settings_cfg = plugins_cfg.setdefault("settings", {})
        current = settings_cfg.get(plugin_id, {})
        if not isinstance(current, dict):
            current = {}
        merged = deep_merge(current, patch)
        self._validate_settings(manifest, merged)
        settings_cfg[plugin_id] = merged
        self._write_user_config(user_cfg)

    def settings_schema_for(self, plugin_id: str) -> dict[str, Any] | None:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        manifest = self._manifest_for(plugin_id, manifests)
        if manifest is None:
            raise KeyError(f"unknown plugin {plugin_id}")
        schema = manifest.settings_schema
        return schema if isinstance(schema, dict) else None
