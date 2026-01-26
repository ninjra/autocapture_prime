"""Plugin discovery and loading."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
from autocapture_nx.kernel.paths import plugins_dir, resolve_repo_path, load_json

from .api import PluginContext
from .host import SubprocessPlugin
from .runtime import network_guard


@dataclass
class LoadedPlugin:
    plugin_id: str
    manifest: dict[str, Any]
    instance: Any
    capabilities: dict[str, Any]


class CapabilityProxy:
    def __init__(self, target: Any, network_allowed: bool) -> None:
        self._target = target
        self._network_allowed = network_allowed

    def __call__(self, *args, **kwargs):
        if not callable(self._target):
            raise TypeError("Capability is not callable")
        with network_guard(self._network_allowed):
            return self._target(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                with network_guard(self._network_allowed):
                    return attr(*args, **kwargs)

            return wrapped
        return attr


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Any] = {}

    def register(self, capability: str, impl: Any, network_allowed: bool) -> None:
        self._capabilities[capability] = CapabilityProxy(impl, network_allowed)

    def get(self, capability: str) -> Any:
        if capability not in self._capabilities:
            raise PluginError(f"Missing capability: {capability}")
        return self._capabilities[capability]

    def all(self) -> dict[str, Any]:
        return dict(self._capabilities)


class PluginRegistry:
    def __init__(self, config: dict[str, Any], safe_mode: bool) -> None:
        self.config = config
        self.safe_mode = safe_mode
        self._validator = SchemaLiteValidator()

    def discover_manifests(self) -> list[Path]:
        paths = [plugins_dir() / "builtin"]
        for extra in self.config.get("plugins", {}).get("search_paths", []):
            paths.append(resolve_repo_path(extra))
        manifests: list[Path] = []
        for root in paths:
            if not root.exists():
                continue
            for manifest in root.rglob("plugin.json"):
                manifests.append(manifest)
        return sorted(manifests)

    def load_lockfile(self) -> dict[str, Any]:
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        lockfile = resolve_repo_path(locks_cfg.get("lockfile", "config/plugin_locks.json"))
        if not lockfile.exists():
            raise PluginError(f"Missing plugin lockfile: {lockfile}")
        try:
            return load_json(lockfile)
        except FileNotFoundError:
            raise PluginError(f"Missing plugin lockfile: {lockfile}")

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        schema_path = resolve_repo_path("contracts/plugin_manifest.schema.json")
        try:
            schema = load_json(schema_path)
        except FileNotFoundError:
            raise PluginError("Missing plugin manifest schema")
        self._validator.validate(schema, manifest)

    def _check_lock(self, plugin_id: str, manifest_path: Path, plugin_root: Path, lockfile: dict[str, Any]) -> None:
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        if not locks_cfg.get("enforce", True):
            return
        plugin_locks = lockfile.get("plugins", {})
        if plugin_id not in plugin_locks:
            raise PluginError(f"Plugin {plugin_id} missing from lockfile")
        expected = plugin_locks[plugin_id]
        manifest_hash = sha256_file(manifest_path)
        artifact_hash = sha256_directory(plugin_root)
        if manifest_hash != expected.get("manifest_sha256"):
            raise PluginError(f"Plugin {plugin_id} manifest hash mismatch")
        if artifact_hash != expected.get("artifact_sha256"):
            raise PluginError(f"Plugin {plugin_id} artifact hash mismatch")

    def _check_permissions(self, manifest: dict[str, Any]) -> None:
        perms = manifest.get("permissions", {})
        if perms.get("network", False):
            allowed = set(
                self.config.get("plugins", {})
                .get("permissions", {})
                .get("network_allowed_plugin_ids", [])
            )
            if manifest.get("plugin_id") not in allowed:
                raise PluginError("Network permission denied by policy")

    def load_plugins(self) -> tuple[list[LoadedPlugin], CapabilityRegistry]:
        manifests = self.discover_manifests()
        lockfile = self.load_lockfile()
        allowlist = set(self.config.get("plugins", {}).get("allowlist", []))
        enabled_map = self.config.get("plugins", {}).get("enabled", {})
        default_pack = set(self.config.get("plugins", {}).get("default_pack", []))
        hosting_cfg = self.config.get("plugins", {}).get("hosting", {})
        hosting_mode = hosting_cfg.get("mode", "inproc")
        inproc_allowlist = set(hosting_cfg.get("inproc_allowlist", []))

        manifests_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
        for manifest_path in manifests:
            with manifest_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self._validate_manifest(manifest)
            plugin_id = manifest["plugin_id"]
            manifests_by_id[plugin_id] = (manifest_path, manifest)

        loaded: list[LoadedPlugin] = []
        capabilities = CapabilityRegistry()

        def is_enabled(pid: str, manifest: dict[str, Any]) -> bool:
            if self.config.get("plugins", {}).get("safe_mode", False):
                return pid in default_pack
            if pid in enabled_map:
                return bool(enabled_map[pid])
            return bool(manifest.get("enabled", True))

        enabled_set = {
            pid
            for pid, (_path, manifest) in manifests_by_id.items()
            if pid in allowlist and is_enabled(pid, manifest)
        }

        for plugin_id, (manifest_path, manifest) in manifests_by_id.items():
            if plugin_id not in allowlist:
                continue
            if plugin_id not in enabled_set:
                continue
            depends = manifest.get("depends_on", [])
            for dep in depends:
                if dep not in allowlist:
                    raise PluginError(f"Plugin {plugin_id} depends on non-allowlisted {dep}")
                if dep not in enabled_set:
                    raise PluginError(f"Plugin {plugin_id} depends on disabled {dep}")
            self._check_permissions(manifest)
            self._check_lock(plugin_id, manifest_path, manifest_path.parent, lockfile)

            entrypoints = manifest.get("entrypoints", [])
            if not entrypoints:
                raise PluginError(f"Plugin {plugin_id} has no entrypoints")
            for entry in entrypoints:
                module_path = manifest_path.parent / entry["path"]
                if not module_path.exists():
                    raise PluginError(f"Missing entrypoint module {module_path}")
                module_name = f"autocapture_plugin_{plugin_id.replace('.', '_')}"
                network_allowed = bool(manifest.get("permissions", {}).get("network", False))
                if hosting_mode == "subprocess" and plugin_id not in inproc_allowlist:
                    instance = SubprocessPlugin(module_path, entry["callable"], plugin_id, network_allowed, self.config)
                    caps = instance.capabilities()
                else:
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    if spec is None or spec.loader is None:
                        raise PluginError(f"Cannot load module {module_path}")
                    module = importlib.util.module_from_spec(spec)
                    import sys

                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)  # type: ignore[call-arg]
                    factory = getattr(module, entry["callable"], None)
                    if factory is None:
                        raise PluginError(f"Missing callable {entry['callable']} in {module_path}")

                    context = PluginContext(
                        config=self.config,
                        get_capability=capabilities.get,
                        logger=lambda msg: None,
                    )
                    with network_guard(network_allowed):
                        instance = factory(plugin_id, context)
                        if not hasattr(instance, "capabilities"):
                            raise PluginError(f"Plugin {plugin_id} missing capabilities()")
                        caps = instance.capabilities()
                for cap_name, impl in caps.items():
                    capabilities.register(cap_name, impl, network_allowed)
                loaded.append(LoadedPlugin(plugin_id, manifest, instance, caps))

        return loaded, capabilities
