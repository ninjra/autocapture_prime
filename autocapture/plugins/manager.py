"""MX plugin manager."""

from __future__ import annotations

import importlib
import importlib.util
import json
import hashlib
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from autocapture.plugins.manifest import ExtensionManifest, PluginManifest

_DEPRECATION_WARNED = False


@dataclass
class ExtensionInstance:
    plugin_id: str
    manifest: ExtensionManifest
    instance: Any


class PluginManager:
    def __init__(self, config: dict[str, Any], safe_mode: bool = False) -> None:
        global _DEPRECATION_WARNED
        if not _DEPRECATION_WARNED:
            warnings.warn(
                "autocapture.plugins.PluginManager is deprecated; migrate to autocapture_nx.plugin_system.",
                DeprecationWarning,
                stacklevel=2,
            )
            _DEPRECATION_WARNED = True
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
        seen: set[str] = set()
        unique: list[Path] = []
        for path in paths:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

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
        importlib.invalidate_caches()
        module = importlib.import_module(module_name)
        if force_reload:
            source_file = str(getattr(module, "__file__", "") or "")
            if source_file:
                try:
                    cache_file = importlib.util.cache_from_source(source_file)
                    Path(cache_file).unlink(missing_ok=True)
                except Exception:
                    pass
            module = importlib.reload(module)
        factory = getattr(module, callable_name)
        if not callable(factory):
            raise TypeError(f"Factory not callable: {factory_path}")
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
                try:
                    factory = self._load_factory(ext.factory, force_reload=force_reload)
                    instance = factory(manifest.plugin_id)
                except Exception as exc:
                    raise RuntimeError(
                        "plugin_factory_load_failed:"
                        f"plugin_id={manifest.plugin_id};"
                        f"extension={ext.name};"
                        f"kind={ext.kind};"
                        f"factory={ext.factory};"
                        f"manifest={manifest.path};"
                        f"error={type(exc).__name__}:{exc}"
                    ) from exc
                if force_reload:
                    self._reload_plugins.discard(manifest.plugin_id)
                wrapped = ExtensionInstance(plugin_id=manifest.plugin_id, manifest=ext, instance=instance)
                self._extension_cache[cache_key] = wrapped
                return wrapped
        raise KeyError(f"No enabled extension for kind '{kind}'")


def load_json_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
