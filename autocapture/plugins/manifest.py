"""MX plugin manifest loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ExtensionManifest:
    kind: str
    factory: str
    name: str
    version: str
    caps: list[str]
    pillars: dict[str, Any]


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    schema_version: int
    version: str
    display_name: str
    description: str
    extensions: list[ExtensionManifest]
    path: Path

    @classmethod
    def from_path(cls, path: Path) -> "PluginManifest":
        data = _load_manifest(path)
        schema_version = int(data.get("schema_version", 0))
        plugin_id = str(data.get("plugin_id", ""))
        version = str(data.get("version", ""))
        display_name = str(data.get("display_name", ""))
        description = str(data.get("description", ""))
        raw_ext = data.get("extensions", [])
        extensions = [
            ExtensionManifest(
                kind=str(ext.get("kind", "")),
                factory=str(ext.get("factory", "")),
                name=str(ext.get("name", "")),
                version=str(ext.get("version", "")),
                caps=list(ext.get("caps", []) or []),
                pillars=dict(ext.get("pillars", {}) or {}),
            )
            for ext in raw_ext
        ]
        if not plugin_id:
            raise ValueError(f"plugin_id missing in manifest {path}")
        if schema_version <= 0:
            raise ValueError(f"schema_version missing in manifest {path}")
        return cls(
            plugin_id=plugin_id,
            schema_version=schema_version,
            version=version,
            display_name=display_name,
            description=description,
            extensions=extensions,
            path=path,
        )


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))
