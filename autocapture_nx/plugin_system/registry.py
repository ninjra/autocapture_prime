"""Plugin discovery and loading."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from autocapture_nx import __version__ as kernel_version
from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
from autocapture_nx.kernel.paths import plugins_dir, resolve_repo_path, load_json

from .api import PluginContext
from .host import SubprocessPlugin
from .manifest import PluginManifest
from .runtime import network_guard

if TYPE_CHECKING:
    from autocapture_nx.kernel.system import System


DEFAULT_CAPABILITY_POLICY: dict[str, Any] = {
    "mode": "single",
    "preferred": [],
    "provider_ids": [],
    "fanout": True,
    "max_providers": 0,
}


def _parse_version(version: str) -> tuple[int, ...]:
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


def _version_satisfies(current: str, requirement: str) -> bool:
    ops = (">=", "<=", ">", "<", "==")
    op = "=="
    target = requirement.strip()
    for candidate in ops:
        if target.startswith(candidate):
            op = candidate
            target = target[len(candidate) :].strip()
            break
    current_v = _parse_version(current)
    target_v = _parse_version(target)
    if op == ">=":
        return current_v >= target_v
    if op == "<=":
        return current_v <= target_v
    if op == ">":
        return current_v > target_v
    if op == "<":
        return current_v < target_v
    return current_v == target_v


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

    @property
    def network_allowed(self) -> bool:
        return self._network_allowed

    @property
    def target(self) -> Any:
        return self._target

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


class MultiCapabilityProxy:
    """Fan-out proxy that can expose multiple providers for a capability."""

    def __init__(
        self,
        capability: str,
        providers: list[tuple[str, CapabilityProxy]],
        policy: dict[str, Any],
    ) -> None:
        self.capability = capability
        self._policy = dict(policy)
        self._providers: list[tuple[str, CapabilityProxy]] = []
        for plugin_id, proxy in providers:
            self.add_provider(plugin_id, proxy)

    def add_provider(self, plugin_id: str, proxy: CapabilityProxy) -> None:
        for existing_id, _ in self._providers:
            if existing_id == plugin_id:
                raise PluginError(f"Duplicate provider {plugin_id} for capability {self.capability}")
        self._providers.append((plugin_id, proxy))
        max_providers = int(self._policy.get("max_providers", 0) or 0)
        if max_providers > 0:
            self._providers = self._providers[:max_providers]

    def items(self) -> list[tuple[str, CapabilityProxy]]:
        return list(self._providers)

    def provider_ids(self) -> list[str]:
        return [plugin_id for plugin_id, _proxy in self._providers]

    def call_all(self, method: str, *args, **kwargs) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for plugin_id, proxy in self._providers:
            attr = getattr(proxy, method, None)
            if attr is None:
                continue
            if callable(attr):
                result = attr(*args, **kwargs)
            else:
                result = attr
            results.append({"plugin_id": plugin_id, "result": result})
        return results

    def __getattr__(self, name: str) -> Any:
        def _fanout(*args, **kwargs):
            return self.call_all(name, *args, **kwargs)

        return _fanout


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

    def replace_all(self, mapping: dict[str, Any]) -> None:
        self._capabilities = dict(mapping)


class PluginRegistry:
    def __init__(self, config: dict[str, Any], safe_mode: bool) -> None:
        self.config = config
        self.safe_mode = safe_mode
        self._validator = SchemaLiteValidator()
        plugins_cfg = config.get("plugins", {}) if isinstance(config, dict) else {}
        self._capability_policies = plugins_cfg.get("capabilities", {}) if isinstance(plugins_cfg, dict) else {}

    def discover_manifest_paths(self) -> list[Path]:
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

    def discover_manifests(self) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        for manifest_path in self.discover_manifest_paths():
            with manifest_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self._validate_manifest(manifest)
            self._check_compat(manifest)
            manifests.append(PluginManifest.from_dict(manifest, manifest_path))
        return manifests

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

    def _check_compat(self, manifest: dict[str, Any]) -> None:
        compat = manifest.get("compat", {})
        requires_kernel = compat.get("requires_kernel")
        if requires_kernel and not _version_satisfies(kernel_version, requires_kernel):
            raise PluginError(f"Plugin {manifest.get('plugin_id')} requires kernel {requires_kernel}, have {kernel_version}")
        required_schemas = compat.get("requires_schema_versions", [])
        if required_schemas:
            schema_version = self.config.get("schema_version")
            if schema_version not in required_schemas:
                raise PluginError(
                    f"Plugin {manifest.get('plugin_id')} requires schema versions {required_schemas}, have {schema_version}"
                )

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

    def validate_allowlist_and_hashes(self, manifests: list[PluginManifest]) -> None:
        allowlist = set(self.config.get("plugins", {}).get("allowlist", []))
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        lockfile = self.load_lockfile() if locks_cfg.get("enforce", True) else {"plugins": {}}
        plugin_locks = lockfile.get("plugins", {})
        for manifest in manifests:
            if manifest.plugin_id not in allowlist:
                raise PluginError(f"Plugin {manifest.plugin_id} not allowlisted")
            if not locks_cfg.get("enforce", True):
                continue
            expected = plugin_locks.get(manifest.plugin_id)
            if not isinstance(expected, dict):
                raise PluginError(f"Plugin {manifest.plugin_id} missing from lockfile")
            manifest_hash = sha256_file(manifest.path)
            artifact_hash = sha256_directory(manifest.path.parent)
            if manifest_hash != expected.get("manifest_sha256"):
                raise PluginError(f"Plugin {manifest.plugin_id} manifest hash mismatch")
            if artifact_hash != expected.get("artifact_sha256"):
                raise PluginError(f"Plugin {manifest.plugin_id} artifact hash mismatch")

    def _capability_policy(self, capability: str) -> dict[str, Any]:
        raw = self._capability_policies.get(capability, {}) if isinstance(self._capability_policies, dict) else {}
        policy = dict(DEFAULT_CAPABILITY_POLICY)
        if isinstance(raw, dict):
            policy.update(raw)
        mode = str(policy.get("mode", "single")).lower()
        if mode not in {"single", "multi"}:
            raise PluginError(f"Invalid capability mode for {capability}: {mode}")
        policy["mode"] = mode
        preferred = policy.get("preferred", [])
        policy["preferred"] = [str(pid) for pid in preferred] if isinstance(preferred, list) else []
        provider_ids = policy.get("provider_ids", [])
        policy["provider_ids"] = [str(pid) for pid in provider_ids] if isinstance(provider_ids, list) else []
        try:
            policy["max_providers"] = int(policy.get("max_providers", 0))
        except Exception:
            policy["max_providers"] = 0
        policy["fanout"] = bool(policy.get("fanout", True))
        return policy

    def _ordered_providers(
        self,
        providers: list[tuple[str, CapabilityProxy]],
        preferred: list[str],
    ) -> list[tuple[str, CapabilityProxy]]:
        base = sorted(providers, key=lambda item: item[0])
        if not preferred:
            return base
        preferred_set = set(preferred)
        head: list[tuple[str, CapabilityProxy]] = []
        for pid in preferred:
            for candidate in base:
                if candidate[0] == pid:
                    head.append(candidate)
        tail = [candidate for candidate in base if candidate[0] not in preferred_set]
        return head + tail

    def _filtered_providers(
        self,
        capability: str,
        providers: list[tuple[str, CapabilityProxy]],
        policy: dict[str, Any],
    ) -> list[tuple[str, CapabilityProxy]]:
        provider_ids = policy.get("provider_ids", [])
        if not provider_ids:
            return providers
        allowed = set(provider_ids)
        filtered = [item for item in providers if item[0] in allowed]
        if not filtered:
            raise PluginError(f"No allowed providers for {capability} after provider_ids filter")
        return filtered

    def _resolve_single(
        self,
        capability: str,
        providers: list[tuple[str, CapabilityProxy]],
        policy: dict[str, Any],
    ) -> tuple[str, CapabilityProxy]:
        if len(providers) == 1:
            return providers[0]
        preferred = policy.get("preferred", [])
        for pid in preferred:
            for candidate in providers:
                if candidate[0] == pid:
                    return candidate
        ids = ", ".join(sorted(pid for pid, _proxy in providers))
        raise PluginError(f"Multiple providers for {capability}: {ids}")

    def _resolve_capabilities(
        self,
        providers_by_cap: dict[str, list[tuple[str, CapabilityProxy]]],
    ) -> CapabilityRegistry:
        capabilities = CapabilityRegistry()
        for capability, providers in sorted(providers_by_cap.items(), key=lambda item: item[0]):
            policy = self._capability_policy(capability)
            providers = self._filtered_providers(capability, providers, policy)
            providers = self._ordered_providers(providers, policy.get("preferred", []))
            if policy.get("mode") == "multi":
                max_providers = int(policy.get("max_providers", 0) or 0)
                if max_providers > 0:
                    providers = providers[:max_providers]
                multi = MultiCapabilityProxy(capability, providers, policy)
                capabilities.register(capability, multi, network_allowed=False)
            else:
                plugin_id, proxy = self._resolve_single(capability, providers, policy)
                capabilities.register(capability, proxy, network_allowed=proxy.network_allowed)
        return capabilities

    def load_enabled(self, manifests: list[PluginManifest], *, safe_mode: bool) -> list[LoadedPlugin]:
        registry = self if safe_mode == self.safe_mode else PluginRegistry(self.config, safe_mode=safe_mode)
        loaded, _caps = registry.load_plugins()
        allowed_ids = {manifest.plugin_id for manifest in manifests}
        return [plugin for plugin in loaded if plugin.plugin_id in allowed_ids]

    def register_capabilities(self, plugins: list[Any], system: System) -> None:
        from autocapture_nx.kernel.system import System as SystemType

        if not isinstance(system, SystemType):
            raise PluginError("register_capabilities requires a System instance")
        for plugin in plugins:
            if isinstance(plugin, LoadedPlugin):
                plugin_id = plugin.plugin_id
                caps = plugin.capabilities
                network_allowed = bool(plugin.manifest.get("permissions", {}).get("network", False))
            elif hasattr(plugin, "capabilities"):
                plugin_id = str(getattr(plugin, "plugin_id", "unknown.plugin"))
                caps = plugin.capabilities()
                network_allowed = False
            else:
                continue
            for cap_name, impl in caps.items():
                policy = self._capability_policy(cap_name)
                if system.has(cap_name):
                    if policy.get("mode") != "multi":
                        raise PluginError(f"Duplicate capability for {cap_name}: {plugin_id}")
                    existing = system.get(cap_name)
                    if isinstance(existing, CapabilityProxy):
                        existing = existing.target
                    if isinstance(existing, MultiCapabilityProxy):
                        existing.add_provider(plugin_id, CapabilityProxy(impl, network_allowed))
                        continue
                    raise PluginError(f"Existing capability for {cap_name} is not multi-capable")
                if policy.get("mode") == "multi":
                    multi = MultiCapabilityProxy(
                        cap_name,
                        [(plugin_id, CapabilityProxy(impl, network_allowed))],
                        policy,
                    )
                    system.register(cap_name, multi, network_allowed=False)
                else:
                    system.register(cap_name, impl, network_allowed=network_allowed)

    def load_plugins(self) -> tuple[list[LoadedPlugin], CapabilityRegistry]:
        manifests = self.discover_manifest_paths()
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
            self._check_compat(manifest)
            plugin_id = manifest["plugin_id"]
            manifests_by_id[plugin_id] = (manifest_path, manifest)

        loaded: list[LoadedPlugin] = []
        capabilities = CapabilityRegistry()
        providers_by_cap: dict[str, list[tuple[str, CapabilityProxy]]] = {}

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
                    proxy = CapabilityProxy(impl, network_allowed)
                    providers_by_cap.setdefault(cap_name, []).append((plugin_id, proxy))
                loaded.append(LoadedPlugin(plugin_id, manifest, instance, caps))

        resolved = self._resolve_capabilities(providers_by_cap)
        capabilities.replace_all(resolved.all())
        return loaded, capabilities
