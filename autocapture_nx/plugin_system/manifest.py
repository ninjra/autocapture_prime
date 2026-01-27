"""NX plugin manifest models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class PluginEntrypoint:
    kind: str
    id: str
    path: str
    callable: str


@dataclass(frozen=True)
class PluginPermissions:
    filesystem: str
    gpu: bool
    raw_input: bool
    network: bool


@dataclass(frozen=True)
class PluginCompat:
    requires_kernel: str
    requires_schema_versions: List[int]


@dataclass(frozen=True)
class PluginHashLock:
    manifest_sha256: str
    artifact_sha256: str


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    enabled: bool
    entrypoints: List[PluginEntrypoint]
    permissions: PluginPermissions
    compat: PluginCompat
    depends_on: List[str]
    conflicts_with: List[str]
    replaces: List[str]
    stages: List[str]
    hash_lock: PluginHashLock
    path: Path

    @classmethod
    def from_dict(cls, data: Dict[str, Any], path: Path) -> "PluginManifest":
        entrypoints = [
            PluginEntrypoint(
                kind=str(entry.get("kind", "")),
                id=str(entry.get("id", "")),
                path=str(entry.get("path", "")),
                callable=str(entry.get("callable", "")),
            )
            for entry in data.get("entrypoints", []) or []
        ]
        perms = data.get("permissions", {}) or {}
        permissions = PluginPermissions(
            filesystem=str(perms.get("filesystem", "none")),
            gpu=bool(perms.get("gpu", False)),
            raw_input=bool(perms.get("raw_input", False)),
            network=bool(perms.get("network", False)),
        )
        compat_raw = data.get("compat", {}) or {}
        compat = PluginCompat(
            requires_kernel=str(compat_raw.get("requires_kernel", "")),
            requires_schema_versions=list(compat_raw.get("requires_schema_versions", []) or []),
        )
        lock_raw = data.get("hash_lock", {}) or {}
        lock = PluginHashLock(
            manifest_sha256=str(lock_raw.get("manifest_sha256", "")),
            artifact_sha256=str(lock_raw.get("artifact_sha256", "")),
        )
        return cls(
            plugin_id=str(data.get("plugin_id", "")),
            version=str(data.get("version", "")),
            enabled=bool(data.get("enabled", True)),
            entrypoints=entrypoints,
            permissions=permissions,
            compat=compat,
            depends_on=list(data.get("depends_on", []) or []),
            conflicts_with=list(data.get("conflicts_with", []) or []),
            replaces=list(data.get("replaces", []) or []),
            stages=list(data.get("stages", []) or []),
            hash_lock=lock,
            path=path,
        )
