"""NX plugin manager for discovery and policy settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autocapture_nx.kernel.hashing import sha256_directory, sha256_file

from .manifest import PluginManifest
from .registry import PluginRegistry


@dataclass(frozen=True)
class PluginStatus:
    plugin_id: str
    enabled: bool
    allowlisted: bool
    hash_ok: bool
    version: str
    permissions: Dict[str, Any]
    depends_on: List[str]


class PluginManager:
    def __init__(self, config: dict[str, Any], safe_mode: bool = False) -> None:
        self.config = config
        self.safe_mode = safe_mode
        self._registry = PluginRegistry(config, safe_mode=safe_mode)

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

    def _enabled_plugin_ids(self, manifests: list[PluginManifest]) -> set[str]:
        allowlist = set(self.config.get("plugins", {}).get("allowlist", []))
        enabled_map = self.config.get("plugins", {}).get("enabled", {})
        default_pack = set(self.config.get("plugins", {}).get("default_pack", []))
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

    def list_plugins(self) -> list[PluginStatus]:
        manifests = self._registry.discover_manifests()
        enabled_ids = self._enabled_plugin_ids(manifests)
        allowlist = set(self.config.get("plugins", {}).get("allowlist", []))
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        lockfile = self._registry.load_lockfile() if locks_cfg.get("enforce", True) else {"plugins": {}}
        plugin_locks = lockfile.get("plugins", {})
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
                )
            )
        return sorted(rows, key=lambda r: r.plugin_id)

    def enable(self, plugin_id: str) -> None:
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        enabled_map = plugins_cfg.setdefault("enabled", {})
        enabled_map[plugin_id] = True
        self._write_user_config(user_cfg)

    def disable(self, plugin_id: str) -> None:
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        enabled_map = plugins_cfg.setdefault("enabled", {})
        enabled_map[plugin_id] = False
        self._write_user_config(user_cfg)

    def approve_hashes(self) -> Dict[str, Any]:
        from tools.hypervisor.scripts.update_plugin_locks import update_plugin_locks

        return update_plugin_locks()
