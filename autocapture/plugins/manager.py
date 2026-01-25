"""MX plugin manager."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from autocapture.plugins.manifest import ExtensionManifest, PluginManifest


@dataclass
class ExtensionInstance:
    plugin_id: str
    manifest: ExtensionManifest
    instance: Any


class PluginManager:
    def __init__(self, config: dict[str, Any], safe_mode: bool = False) -> None:
        self.config = config
        self.safe_mode = safe_mode
        self._manifests: list[PluginManifest] = []
        self._extension_cache: dict[tuple[str, str], ExtensionInstance] = {}
        self._manifest_mtimes: dict[Path, float] = {}
        self._manifest_hashes: dict[Path, str] = {}
        self._reload_plugins: set[str] = set()
        self._discover()

    def _discover(self) -> None:
        manifests = []
        for path in self._manifest_paths():
            manifests.append(PluginManifest.from_path(path))
            self._manifest_mtimes[path] = path.stat().st_mtime_ns
            self._manifest_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        self._manifests = manifests

    def _manifest_paths(self) -> list[Path]:
        paths: list[Path] = []
        builtin_root = Path("autocapture_plugins")
        if builtin_root.exists():
            for ext in (".yaml", ".yml", ".json"):
                paths.extend(sorted(builtin_root.rglob(f"*{ext}")))
        if not self.safe_mode:
            for extra in self.config.get("plugins", {}).get("search_paths", []):
                root = Path(extra)
                if not root.exists():
                    continue
                for ext in (".yaml", ".yml", ".json"):
                    paths.extend(sorted(root.rglob(f"*{ext}")))
        return paths

    def _enabled_plugins(self) -> set[str]:
        allowlist = set(self.config.get("plugins", {}).get("allowlist", []))
        enabled_map = self.config.get("plugins", {}).get("enabled", {})
        default_pack = set(self.config.get("plugins", {}).get("default_pack", []))

        enabled: set[str] = set()
        for manifest in self._manifests:
            pid = manifest.plugin_id
            if allowlist and pid not in allowlist:
                continue
            if self.safe_mode:
                if pid not in default_pack:
                    continue
                if not self._safe_extensions(manifest.extensions):
                    continue
                enabled.add(pid)
                continue
            if pid in enabled_map:
                if enabled_map.get(pid):
                    enabled.add(pid)
            else:
                enabled.add(pid)
        return enabled

    def _safe_extensions(self, extensions: list[ExtensionManifest]) -> bool:
        for ext in extensions:
            security = (ext.pillars or {}).get("security", {})
            network_access = security.get("network_access", "none")
            sandbox = security.get("sandbox", "inproc")
            if sandbox != "inproc":
                return False
            if network_access not in ("none", "localhost"):
                return False
        return True

    def list_plugins(self) -> list[dict[str, Any]]:
        enabled = self._enabled_plugins()
        rows = []
        for manifest in self._manifests:
            rows.append(
                {
                    "plugin_id": manifest.plugin_id,
                    "enabled": manifest.plugin_id in enabled,
                    "path": str(manifest.path),
                }
            )
        return sorted(rows, key=lambda r: r["plugin_id"])

    def list_extensions(self) -> list[dict[str, Any]]:
        enabled = self._enabled_plugins()
        rows = []
        for manifest in self._manifests:
            for ext in manifest.extensions:
                rows.append(
                    {
                        "plugin_id": manifest.plugin_id,
                        "kind": ext.kind,
                        "name": ext.name,
                        "version": ext.version,
                        "enabled": manifest.plugin_id in enabled,
                    }
                )
        return sorted(rows, key=lambda r: (r["kind"], r["plugin_id"], r["name"]))

    def refresh(self) -> list[str]:
        """Reload manifests if they changed. Returns plugin_ids reloaded."""
        reloaded: list[str] = []
        for path, last_mtime in list(self._manifest_mtimes.items()):
            if not path.exists():
                continue
            mtime = path.stat().st_mtime_ns
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if mtime != last_mtime or digest != self._manifest_hashes.get(path):
                manifest = PluginManifest.from_path(path)
                self._manifest_mtimes[path] = mtime
                self._manifest_hashes[path] = digest
                self._manifests = [m for m in self._manifests if m.path != path] + [manifest]
                reloaded.append(manifest.plugin_id)
                self._reload_plugins.add(manifest.plugin_id)
                self._extension_cache = {
                    key: value
                    for key, value in self._extension_cache.items()
                    if key[0] != manifest.plugin_id
                }
        return reloaded

    def _load_factory(self, factory_path: str, force_reload: bool) -> Callable[..., Any]:
        if ":" not in factory_path:
            raise ValueError(f"Invalid factory path: {factory_path}")
        module_name, callable_name = factory_path.split(":", 1)
        if force_reload:
            spec = importlib.util.find_spec(module_name)
            if spec and spec.origin:
                source = Path(spec.origin).read_text(encoding="utf-8")
                code = compile(source, spec.origin, "exec")
                import types
                import sys

                module = types.ModuleType(module_name)
                module.__file__ = spec.origin
                exec(code, module.__dict__)
                sys.modules[module_name] = module
            else:
                module = importlib.import_module(module_name)
        else:
            module = importlib.import_module(module_name)
        factory = getattr(module, callable_name)
        return factory

    def get_extension(self, kind: str, name: str | None = None) -> ExtensionInstance:
        enabled = self._enabled_plugins()
        for manifest in self._manifests:
            if manifest.plugin_id not in enabled:
                continue
            for ext in manifest.extensions:
                if ext.kind != kind:
                    continue
                if name and ext.name != name:
                    continue
                cache_key = (manifest.plugin_id, ext.name)
                if cache_key in self._extension_cache:
                    return self._extension_cache[cache_key]
                force_reload = manifest.plugin_id in self._reload_plugins
                factory = self._load_factory(ext.factory, force_reload=force_reload)
                instance = factory(manifest.plugin_id)
                if force_reload:
                    self._reload_plugins.discard(manifest.plugin_id)
                wrapped = ExtensionInstance(plugin_id=manifest.plugin_id, manifest=ext, instance=instance)
                self._extension_cache[cache_key] = wrapped
                return wrapped
        raise KeyError(f"No enabled extension for kind '{kind}'")


def load_json_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
