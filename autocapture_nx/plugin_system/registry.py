"""Plugin discovery and loading."""

from __future__ import annotations

import importlib.util
import json
import os
import random
import site
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING, cast

from autocapture_nx import __version__ as kernel_version
from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.audit import PluginAuditLog, hash_payload
from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file, clear_directory_hash_cache
from autocapture_nx.kernel.paths import plugins_dir, resolve_repo_path, load_json
from autocapture_nx.kernel.schema_registry import SchemaRegistry, derive_schema_from_paths
from autocapture_nx.kernel.rng import RNGScope, RNGService, install_rng_guard

from .api import PluginContext
from .contracts import IOContract, load_io_contracts
from .host import SubprocessPlugin, estimate_rows_read, estimate_rows_written
from .manifest import PluginManifest
from .runtime import FilesystemPolicy, filesystem_guard, network_guard
from .settings import build_plugin_settings
from .trace import PluginExecutionTrace, PluginLoadReport

if TYPE_CHECKING:
    from autocapture_nx.kernel.system import System


DEFAULT_CAPABILITY_POLICY: dict[str, Any] = {
    "mode": "single",
    "preferred": [],
    "provider_ids": [],
    "fanout": True,
    "max_providers": 0,
    "failure_ordering": {},
}


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    if a <= b:
        return a, b
    return b, a


def _normalize_tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    tags = [str(item).strip() for item in raw if str(item).strip()]
    return sorted(set(tags))


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


def _is_wsl() -> bool:
    # Best-effort detection for WSL2. This is used only for resource safety
    # defaults and must not affect non-WSL behavior when explicitly configured.
    if os.getenv("WSL_INTEROP") or os.getenv("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False


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


def _capability_guard(capabilities, plugin_id: str, required_capabilities: set[str] | None):
    if required_capabilities is None:
        required_capabilities = set()
    allowed = set(required_capabilities)

    def _get_capability(name: str):
        if name not in allowed:
            # Treat this as a plugin contract violation (not a host OS permission
            # error) so callers can handle it deterministically.
            raise PluginError(f"capability_not_allowed:{plugin_id}:{name}")
        return capabilities.get(name)

    return _get_capability


@dataclass
class LoadedPlugin:
    plugin_id: str
    manifest: dict[str, Any]
    instance: Any
    capabilities: dict[str, Any]
    filesystem_policy: FilesystemPolicy | None = None
    manifest_path: Path | None = None


_TEMP_ENV_LOCK = None


def _temporary_tempdir_env(temp_dir: str | None):
    """Best-effort temporary TMPDIR/TMP/TEMP override.

    Some OCR backends (notably pytesseract) write temp files and will fail under the
    filesystem guard unless the temp directory is within the plugin's allowed roots.

    Note: os.environ and tempfile.tempdir are process-global. We serialize to avoid
    cross-plugin races. This trades concurrency for determinism and WSL stability.
    """

    import contextlib
    import tempfile
    import threading
    from pathlib import Path

    global _TEMP_ENV_LOCK
    if _TEMP_ENV_LOCK is None:
        # Capability calls can nest (capability A calls capability B). Use a
        # re-entrant lock to avoid deadlocking when nested calls attempt to
        # apply the same tempdir override.
        _TEMP_ENV_LOCK = threading.RLock()

    @contextlib.contextmanager
    def _ctx():
        td = str(temp_dir or "").strip()
        if not td:
            yield
            return
        with _TEMP_ENV_LOCK:
            Path(td).mkdir(parents=True, exist_ok=True)
            prev = {k: os.environ.get(k) for k in ("TMPDIR", "TMP", "TEMP")}
            try:
                os.environ["TMPDIR"] = td
                os.environ["TMP"] = td
                os.environ["TEMP"] = td
                tempfile.tempdir = None
                yield
            finally:
                for k, v in prev.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                tempfile.tempdir = None

    return _ctx()


class CapabilityProxy:
    def __init__(
        self,
        target: Any,
        network_allowed: bool,
        filesystem_policy: FilesystemPolicy | None = None,
        *,
        capability: str | None = None,
        io_contracts: dict[str, IOContract] | None = None,
        schema_registry: SchemaRegistry | None = None,
        rng_seed: int | None = None,
        rng_strict: bool = False,
        rng_enabled: bool = False,
        plugin_id: str | None = None,
        trace_hook: Any | None = None,
        audit_log: PluginAuditLog | None = None,
        audit_run_id: str | None = None,
        audit_code_hash: str | None = None,
        audit_settings_hash: str | None = None,
        temp_dir: str | None = None,
    ) -> None:
        self._target = target
        self._network_allowed = network_allowed
        self._filesystem_policy = filesystem_policy
        self._capability = capability or ""
        self._io_contracts = io_contracts or {}
        self._schema_registry = schema_registry
        self._rng_seed = rng_seed
        self._rng_strict = rng_strict
        self._rng_enabled = rng_enabled
        self._plugin_id = str(plugin_id or "")
        self._trace_hook = trace_hook
        self._audit_log = audit_log
        self._audit_run_id = str(audit_run_id or "").strip()
        self._audit_code_hash = str(audit_code_hash or "").strip() or None
        self._audit_settings_hash = str(audit_settings_hash or "").strip() or None
        self._temp_dir = str(temp_dir or "").strip()

    @property
    def network_allowed(self) -> bool:
        return self._network_allowed

    @property
    def target(self) -> Any:
        return self._target

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    def _validate_input(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        contract = self._io_contracts.get(method)
        if contract is None or contract.input_schema is None or self._schema_registry is None:
            return
        payload = {"args": list(args), "kwargs": dict(kwargs)}
        issues = self._schema_registry.validate(contract.input_schema, payload)
        if issues:
            raise PluginError(
                f"I/O contract input invalid for {self._capability}.{method}: "
                f"{self._schema_registry.format_issues(issues)}"
            )

    def _validate_output(self, method: str, result: Any) -> None:
        contract = self._io_contracts.get(method)
        if contract is None or contract.output_schema is None or self._schema_registry is None:
            return
        issues = self._schema_registry.validate(contract.output_schema, result)
        if issues:
            raise PluginError(
                f"I/O contract output invalid for {self._capability}.{method}: "
                f"{self._schema_registry.format_issues(issues)}"
            )

    def _invoke(self, method: str, func, args: tuple[Any, ...], kwargs: dict[str, Any]):
        from datetime import datetime, timezone
        import time

        self._validate_input(method, args, kwargs)
        start_utc = datetime.now(timezone.utc).isoformat()
        start_perf = time.perf_counter()
        ok = True
        error = None
        audit_error_text: str | None = None
        audit_result: Any = None
        try:
            with RNGScope(self._rng_seed, strict=self._rng_strict, enabled=self._rng_enabled):
                with network_guard(self._network_allowed):
                    # Apply filesystem policy before tempdir override. The override may
                    # create the temp directory, and that must be evaluated against
                    # the callee plugin's policy (not the caller's), especially for
                    # nested capability calls.
                    with filesystem_guard(self._filesystem_policy):
                        with _temporary_tempdir_env(self._temp_dir):
                            result = func(*args, **kwargs)
            self._validate_output(method, result)
            audit_result = result
        except Exception as exc:
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            audit_error_text = error
            raise
        finally:
            end_utc = datetime.now(timezone.utc).isoformat()
            duration_ms = int(max(0.0, (time.perf_counter() - start_perf) * 1000.0))
            if callable(self._trace_hook) and self._plugin_id:
                try:
                    self._trace_hook(
                        {
                            "plugin_id": self._plugin_id,
                            "capability": self._capability,
                            "method": method,
                            "start_utc": start_utc,
                            "end_utc": end_utc,
                            "duration_ms": duration_ms,
                            "ok": bool(ok),
                            "error": error,
                        }
                    )
                except Exception:
                    pass
            # Always audit in-proc capability execution via the same append-only audit DB.
            # Subprocess-hosted plugins already record audit rows inside PluginHostSubprocess.
            if self._audit_log is not None and self._plugin_id and self._capability:
                try:
                    run_id = self._audit_run_id or "run"
                    input_hash, input_bytes = hash_payload({"args": list(args), "kwargs": dict(kwargs)})
                    output_hash, output_bytes = hash_payload(audit_result) if ok else (None, None)
                    data_hash, _ = hash_payload({"input": input_hash, "output": output_hash})
                    rows_written = estimate_rows_written(method, list(args), dict(kwargs))
                    rows_read = estimate_rows_read(method, audit_result) if ok else None
                    self._audit_log.record(
                        run_id=run_id,
                        plugin_id=self._plugin_id,
                        capability=str(self._capability),
                        method=str(method),
                        ok=bool(ok),
                        error=audit_error_text,
                        duration_ms=duration_ms,
                        rows_read=rows_read,
                        rows_written=rows_written,
                        memory_rss_mb=None,
                        memory_vms_mb=None,
                        input_hash=input_hash,
                        output_hash=output_hash,
                        data_hash=data_hash,
                        code_hash=self._audit_code_hash,
                        settings_hash=self._audit_settings_hash,
                        input_bytes=input_bytes,
                        output_bytes=output_bytes,
                    )
                except Exception:
                    pass
        if ok:
            return result
        return None

    def __call__(self, *args, **kwargs):
        if not callable(self._target):
            raise TypeError("Capability is not callable")
        return self._invoke("__call__", self._target, args, kwargs)

    def __getattr__(self, name: str) -> Any:
        # Nested capability usage can access attributes that lazily initialize
        # underlying resources (for example, storage adapters). Resolve the
        # attribute under the callee capability's guards so we do not leak the
        # caller plugin's stricter filesystem/network policy into the callee.
        with network_guard(self._network_allowed):
            with filesystem_guard(self._filesystem_policy):
                attr = getattr(self._target, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                return self._invoke(name, attr, args, kwargs)

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
        self._providers: dict[str, CapabilityProxy] = {}
        for plugin_id, proxy in providers:
            self.add_provider(plugin_id, proxy)

    @property
    def policy(self) -> dict[str, Any]:
        return dict(self._policy)

    @property
    def fanout(self) -> bool:
        return bool(self._policy.get("fanout", True))

    def add_provider(self, plugin_id: str, proxy: CapabilityProxy) -> None:
        if plugin_id in self._providers:
            raise PluginError(f"Duplicate provider {plugin_id} for capability {self.capability}")
        self._providers[plugin_id] = proxy

    def _ordered_ids(self) -> list[str]:
        ids = sorted(self._providers)
        allowed_ids = self._policy.get("provider_ids", [])
        if isinstance(allowed_ids, list) and allowed_ids:
            allowed = {str(pid) for pid in allowed_ids}
            ids = [pid for pid in ids if pid in allowed]
            if not ids:
                raise PluginError(f"No allowed providers for {self.capability} after provider_ids filter")
        preferred_ids = self._policy.get("preferred", [])
        if isinstance(preferred_ids, list) and preferred_ids:
            preferred = [pid for pid in preferred_ids if pid in ids]
            preferred_set = set(preferred)
            tail = [pid for pid in ids if pid not in preferred_set]
            ids = preferred + tail
        try:
            max_providers = int(self._policy.get("max_providers", 0) or 0)
        except Exception:
            max_providers = 0
        if max_providers > 0:
            ids = ids[:max_providers]
        return ids

    def items(self) -> list[tuple[str, CapabilityProxy]]:
        ids = self._ordered_ids()
        return [(pid, self._providers[pid]) for pid in ids]

    def provider_ids(self) -> list[str]:
        return [plugin_id for plugin_id, _proxy in self.items()]

    def primary(self) -> tuple[str, CapabilityProxy]:
        items = self.items()
        if not items:
            raise PluginError(f"No providers available for capability {self.capability}")
        return items[0]

    def call_all(self, method: str, *args, **kwargs) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for plugin_id, proxy in self.items():
            attr = getattr(proxy, method, None)
            if attr is None:
                continue
            if callable(attr):
                try:
                    result = attr(*args, **kwargs)
                    results.append({"plugin_id": plugin_id, "result": result, "ok": True})
                except Exception as exc:
                    results.append({"plugin_id": plugin_id, "error": str(exc), "ok": False})
                    continue
            else:
                results.append({"plugin_id": plugin_id, "result": attr, "ok": True})
        return results

    def __getattr__(self, name: str) -> Any:
        def _fanout(*args, **kwargs):
            return self.call_all(name, *args, **kwargs)

        return _fanout


class FallbackCapabilityProxy:
    """Single-capability proxy with deterministic provider fallback."""

    def __init__(
        self,
        capability: str,
        providers: list[tuple[str, CapabilityProxy]],
        policy: dict[str, Any],
    ) -> None:
        self.capability = capability
        self._policy = dict(policy)
        self._providers = list(providers)

    def _invoke(self, method: str, *args, **kwargs):
        last_exc: Exception | None = None
        for _plugin_id, proxy in self._providers:
            attr = getattr(proxy, method, None)
            if attr is None:
                continue
            try:
                if callable(attr):
                    return attr(*args, **kwargs)
                return attr
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise PluginError(f"No providers available for capability {self.capability}")

    def __getattr__(self, name: str) -> Any:
        def _call(*args, **kwargs):
            return self._invoke(name, *args, **kwargs)

        return _call

    def __call__(self, *args, **kwargs):
        return self._invoke("__call__", *args, **kwargs)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Any] = {}

    def register(
        self,
        capability: str,
        impl: Any,
        network_allowed: bool,
        filesystem_policy: FilesystemPolicy | None = None,
    ) -> None:
        if isinstance(impl, (CapabilityProxy, MultiCapabilityProxy)):
            self._capabilities[capability] = impl
            return
        self._capabilities[capability] = CapabilityProxy(impl, network_allowed, filesystem_policy)

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
        self._schema_registry = SchemaRegistry()
        self._config_schema = self._schema_registry.load_schema_path("contracts/config_schema.json")
        self._rng_service = RNGService.from_config(config)
        self._audit_log = PluginAuditLog.from_config(config)
        self._trace = PluginExecutionTrace()
        self._plugin_tmp_dirs: dict[str, str] = {}
        self._load_reporter = PluginLoadReport(self.load_report)
        self._failure_summary_cache: dict[str, dict[str, Any]] | None = None
        self._load_report: dict[str, Any] = {"loaded": [], "failed": [], "skipped": [], "errors": []}
        if self._rng_service.enabled:
            install_rng_guard()
        plugins_cfg = config.get("plugins", {}) if isinstance(config, dict) else {}
        self._capability_policies = plugins_cfg.get("capabilities", {}) if isinstance(plugins_cfg, dict) else {}
        self._failure_ordering_cfg = plugins_cfg.get("failure_ordering", {}) if isinstance(plugins_cfg, dict) else {}
        conflicts_cfg = plugins_cfg.get("conflicts", {}) if isinstance(plugins_cfg, dict) else {}
        self._conflicts_enforce = True
        self._conflicts_allow_pairs: set[tuple[str, str]] = set()
        if isinstance(conflicts_cfg, dict):
            self._conflicts_enforce = bool(conflicts_cfg.get("enforce", True))
            allow_pairs = conflicts_cfg.get("allow_pairs", [])
            if isinstance(allow_pairs, list):
                for pair in allow_pairs:
                    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                        continue
                    a = str(pair[0]).strip()
                    b = str(pair[1]).strip()
                    if not a or not b or a == b:
                        continue
                    self._conflicts_allow_pairs.add(_normalize_pair(a, b))

    def load_report(self) -> dict[str, Any]:
        return dict(self._load_report)

    def trace(self) -> PluginExecutionTrace:
        return self._trace

    def load_reporter(self) -> PluginLoadReport:
        return self._load_reporter

    def _record_load_failure(
        self,
        *,
        plugin_id: str | None,
        entrypoint: str | None,
        phase: str,
        error: str,
    ) -> None:
        record = {
            "plugin_id": plugin_id,
            "entrypoint": entrypoint,
            "phase": phase,
            "error": error,
        }
        self._load_report["errors"].append(record)
        try:
            self._audit_log.record_load_failure(
                plugin_id=plugin_id,
                entrypoint=entrypoint,
                phase=phase,
                error=error,
            )
        except Exception:
            return

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
            payload = load_json(lockfile)
        except FileNotFoundError:
            raise PluginError(f"Missing plugin lockfile: {lockfile}")
        # EXT-11: optional lockfile signature verification (enabled via config/env).
        sig_cfg = locks_cfg.get("signature", {}) if isinstance(locks_cfg, dict) else {}
        enforce_sig = bool(sig_cfg.get("enforce", False))
        if os.getenv("AUTOCAPTURE_PLUGINS_LOCKS_REQUIRE_SIGNATURE", "").strip().lower() in {"1", "true", "yes"}:
            enforce_sig = True
        if enforce_sig:
            try:
                from autocapture_nx.plugin_system.lock_signing import verify_lockfile
                from autocapture_nx.kernel.keyring import KeyRing

                storage = self.config.get("storage", {}) if isinstance(self.config, dict) else {}
                crypto = storage.get("crypto", {}) if isinstance(storage, dict) else {}
                keyring_path = str(crypto.get("keyring_path", "data/vault/keyring.json"))
                root_key_path = str(crypto.get("root_key_path", "data/vault/root.key"))
                backend = str(crypto.get("keyring_backend", "auto"))
                credential_name = str(crypto.get("keyring_credential_name", "autocapture.keyring"))
                require_protection = bool(storage.get("encryption_required", False) and os.name == "nt")
                keyring = KeyRing.load(
                    keyring_path,
                    legacy_root_path=root_key_path,
                    require_protection=require_protection,
                    backend=backend,
                    credential_name=credential_name,
                )
                sig_path = sig_cfg.get("path") or (str(lockfile) + ".sig.json")
                report = verify_lockfile(lock_path=lockfile, sig_path=resolve_repo_path(sig_path), keyring=keyring)
                if not report.get("ok", False):
                    raise PluginError(f"plugin_locks signature invalid: {report.get('error')}")
            except PluginError:
                raise
            except Exception as exc:
                raise PluginError(f"plugin_locks signature verify failed: {type(exc).__name__}") from exc
        return payload

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
            schema_version = self.config.get("schema_version", 1)
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
        # EXT-04: compatibility contracts pinned in the lock entry.
        try:
            expected_kernel = expected.get("kernel_api_version")
            if expected_kernel and str(expected_kernel) != str(kernel_version):
                raise PluginError(f"Plugin {plugin_id} kernel_api_version mismatch")
            expected_contract = expected.get("contract_lock_hash") or lockfile.get("contract_lock_hash")
            if expected_contract:
                lock_path = resolve_repo_path("contracts/lock.json")
                actual_contract = sha256_file(lock_path) if lock_path.exists() else None
                if str(expected_contract) != str(actual_contract):
                    raise PluginError(f"Plugin {plugin_id} contract_lock_hash mismatch")
        except PluginError:
            raise
        except Exception:
            pass
        manifest_hash = sha256_file(manifest_path)
        artifact_hash = sha256_directory(plugin_root)
        if manifest_hash != expected.get("manifest_sha256"):
            raise PluginError(f"Plugin {plugin_id} manifest hash mismatch")
        if artifact_hash != expected.get("artifact_sha256"):
            raise PluginError(f"Plugin {plugin_id} artifact hash mismatch")

    def _check_permissions(self, manifest: dict[str, Any]) -> None:
        perms = manifest.get("permissions", {})
        if perms.get("network", False):
            perms_cfg = (
                self.config.get("plugins", {}).get("permissions", {})
                if isinstance(self.config.get("plugins", {}).get("permissions", {}), dict)
                else {}
            )
            allowed_internet = set(perms_cfg.get("network_allowed_plugin_ids", []) or [])
            allowed_localhost = set(perms_cfg.get("localhost_allowed_plugin_ids", []) or [])
            allowed = allowed_internet | allowed_localhost
            if manifest.get("plugin_id") not in allowed:
                raise PluginError("Network permission denied by policy")
            hosting = self.config.get("plugins", {}).get("hosting", {})
            hosting_mode = str(hosting.get("mode", "subprocess")).lower()
            inproc_allowlist = set(hosting.get("inproc_allowlist", []) or [])
            if hosting_mode != "subprocess" or manifest.get("plugin_id") in inproc_allowlist:
                raise PluginError("Network-capable plugins must run in subprocess hosting mode")

    def _network_scope_for_plugin(self, plugin_id: str, *, network_requested: bool) -> str:
        """Return one of: none, localhost, internet.

        - `internet` is reserved for the egress gateway.
        - `localhost` allows loopback-only sockets (enforced via global network deny).
        """
        if not network_requested:
            return "none"
        perms_cfg = (
            self.config.get("plugins", {}).get("permissions", {})
            if isinstance(self.config.get("plugins", {}).get("permissions", {}), dict)
            else {}
        )
        allowed_internet = set(perms_cfg.get("network_allowed_plugin_ids", []) or [])
        allowed_localhost = set(perms_cfg.get("localhost_allowed_plugin_ids", []) or [])
        if plugin_id in allowed_internet:
            return "internet"
        if plugin_id in allowed_localhost:
            return "localhost"
        return "none"

    def _load_inproc_instance(
        self,
        *,
        module_path: Path,
        callable_name: str,
        plugin_id: str,
        plugin_settings: dict[str, Any],
        required_capabilities: set[str],
        capabilities: "CapabilityRegistry",
        network_allowed: bool,
        filesystem_policy: FilesystemPolicy | None,
        rng_seed: int | None,
        rng_seed_hex: str | None,
    ) -> Any:
        module_name = f"autocapture_plugin_{plugin_id.replace('.', '_')}_{callable_name}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise PluginError(f"Failed to load plugin module {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            source = module_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise PluginError(f"Failed to read plugin module {module_path}: {exc}") from exc
        code = compile(source, str(module_path), "exec")
        exec(code, module.__dict__)
        factory = getattr(module, callable_name, None)
        if not callable(factory):
            raise PluginError(f"Plugin entrypoint {callable_name} not callable")
        rng_instance = None
        if self._rng_service.enabled and rng_seed is not None:
            try:
                rng_instance = random.Random(int(rng_seed))
            except Exception:
                rng_instance = random.Random(0)
        get_capability = _capability_guard(capabilities, plugin_id, required_capabilities)
        context = PluginContext(
            config=plugin_settings,
            get_capability=get_capability,
            logger=lambda _m: None,
            rng=rng_instance,
            rng_seed=rng_seed,
            rng_seed_hex=str(rng_seed_hex) if rng_seed_hex is not None else None,
        )
        with RNGScope(rng_seed, strict=self._rng_service.strict, enabled=self._rng_service.enabled):
            with network_guard(network_allowed):
                with filesystem_guard(filesystem_policy):
                    instance = factory(plugin_id, context)
        if isinstance(plugin_settings, dict):
            try:
                instance.settings = dict(plugin_settings)
            except Exception:
                pass
        return instance

    def _resolve_settings_schema(
        self,
        manifest: dict[str, Any],
        *,
        plugin_root: Path,
        settings_paths: list[str],
    ) -> dict[str, Any] | None:
        schema_inline = manifest.get("settings_schema")
        if isinstance(schema_inline, dict):
            return schema_inline
        schema_path = manifest.get("settings_schema_path")
        if schema_path:
            path = Path(str(schema_path))
            if not path.is_absolute():
                plugin_candidate = plugin_root / path
                if plugin_candidate.exists():
                    try:
                        return self._schema_registry.load_schema_path(plugin_candidate)
                    except FileNotFoundError as exc:
                        raise PluginError(f"Missing settings schema: {plugin_candidate}") from exc
            try:
                return self._schema_registry.load_schema_path(path)
            except FileNotFoundError as exc:
                raise PluginError(f"Missing settings schema: {path}") from exc
        if settings_paths:
            return derive_schema_from_paths(self._config_schema, settings_paths)
        return {"type": "object"}

    def _validate_settings_schema(
        self,
        *,
        plugin_id: str,
        schema: dict[str, Any] | None,
        settings: dict[str, Any],
    ) -> None:
        if schema is None:
            return
        issues = self._schema_registry.validate(schema, settings)
        if issues:
            raise PluginError(
                f"Plugin {plugin_id} settings schema invalid: {self._schema_registry.format_issues(issues)}"
            )

    def _compute_code_hash(
        self,
        *,
        manifest_path: Path,
        plugin_root: Path,
        entrypoints: list[dict[str, Any]],
        manifest: dict[str, Any],
    ) -> str | None:
        manifest_hash = sha256_file(manifest_path)
        entry_hashes: dict[str, str] = {}
        for entry in entrypoints:
            rel = str(entry.get("path", "")).strip()
            if not rel:
                continue
            path = plugin_root / rel
            if path.exists() and path.is_file():
                entry_hashes[rel] = sha256_file(path)
        artifact_hash = None
        lock = manifest.get("hash_lock", {})
        if isinstance(lock, dict):
            raw = str(lock.get("artifact_sha256") or "").strip()
            if raw:
                artifact_hash = raw
        payload: dict[str, Any] = {"manifest": manifest_hash, "entrypoints": entry_hashes}
        if artifact_hash:
            payload["artifact"] = artifact_hash
        code_hash, _ = hash_payload(payload)
        return code_hash

    def _validate_inproc_justifications(self, inproc_allowlist: set[str]) -> None:
        hosting_cfg = self.config.get("plugins", {}).get("hosting", {})
        justifications = hosting_cfg.get("inproc_justifications", {}) if isinstance(hosting_cfg, dict) else {}
        if not inproc_allowlist:
            return
        missing = []
        if isinstance(justifications, dict):
            for plugin_id in sorted(inproc_allowlist):
                reason = justifications.get(plugin_id)
                if not reason or not str(reason).strip():
                    missing.append(plugin_id)
        else:
            missing = sorted(inproc_allowlist)
        if missing:
            raise PluginError(f"Missing inproc justification for: {', '.join(missing)}")

    def _manifest_provides(self, manifest: dict[str, Any]) -> set[str]:
        provides: set[str] = set()
        for entry in manifest.get("entrypoints", []) or []:
            kind = entry.get("kind")
            if kind:
                provides.add(str(kind))
        for item in manifest.get("provides", []) or []:
            if item:
                provides.add(str(item))
        return provides

    def _minimal_safe_mode_set(
        self,
        manifests_by_id: dict[str, tuple[Path, dict[str, Any]]],
        allowlist: set[str],
        alias_map: dict[str, str],
    ) -> set[str]:
        kernel_cfg = self.config.get("kernel", {}) if isinstance(self.config, dict) else {}
        required_caps = kernel_cfg.get("required_capabilities", [])
        safe_caps = kernel_cfg.get("safe_mode_required_capabilities", [])
        if isinstance(safe_caps, list) and safe_caps:
            required_caps = safe_caps
        if not isinstance(required_caps, list) or not required_caps:
            return set()

        def _add_providers(cap_name: str, selected: set[str]) -> None:
            candidates = sorted(set(providers_by_cap.get(cap_name, [])))
            if not candidates:
                return
            policy = self._capability_policy(cap_name)
            preferred = policy.get("preferred", [])
            preferred_ids = [pid for pid in preferred if pid in candidates]
            if preferred_ids:
                selected.update(preferred_ids)
                return
            selected.add(candidates[0])
        providers_by_cap: dict[str, list[str]] = {}
        for pid, (_path, manifest) in manifests_by_id.items():
            if pid not in allowlist:
                continue
            for cap in self._manifest_provides(manifest):
                providers_by_cap.setdefault(cap, []).append(pid)
        selected: set[str] = set()
        for cap in required_caps:
            cap_name = str(cap).strip()
            if not cap_name:
                continue
            _add_providers(cap_name, selected)
        queue = list(selected)
        while queue:
            pid = queue.pop()
            manifest_entry = manifests_by_id.get(pid)
            if manifest_entry is None:
                continue
            deps = manifest_entry[1].get("depends_on", []) or []
            for dep in deps:
                dep_id = alias_map.get(str(dep).strip(), str(dep).strip())
                if not dep_id or dep_id not in allowlist:
                    continue
                if dep_id not in selected:
                    selected.add(dep_id)
                    queue.append(dep_id)
            required_raw = manifest_entry[1].get("required_capabilities", [])
            if isinstance(required_raw, list):
                for cap in required_raw:
                    cap_name = str(cap).strip()
                    if not cap_name:
                        continue
                    before = set(selected)
                    _add_providers(cap_name, selected)
                    for new_pid in sorted(selected - before):
                        queue.append(new_pid)
        return selected

    def _plugin_load_order(
        self,
        manifests_by_id: dict[str, tuple[Path, dict[str, Any]]],
        enabled_set: set[str],
    ) -> list[str]:
        provided_by_cap: dict[str, list[str]] = {}
        for pid, (_path, manifest) in manifests_by_id.items():
            if pid not in enabled_set:
                continue
            entrypoints = manifest.get("entrypoints", [])
            if not isinstance(entrypoints, list):
                continue
            for entry in entrypoints:
                if not isinstance(entry, dict):
                    continue
                kind = entry.get("kind")
                if isinstance(kind, str) and kind.strip():
                    provided_by_cap.setdefault(kind, []).append(pid)
            provides = manifest.get("provides", [])
            if isinstance(provides, list):
                for cap in provides:
                    capability = str(cap).strip()
                    if capability:
                        provided_by_cap.setdefault(capability, []).append(pid)

        deps: dict[str, set[str]] = {pid: set() for pid in enabled_set}
        for pid, (_path, manifest) in manifests_by_id.items():
            if pid not in enabled_set:
                continue
            depends = manifest.get("depends_on", [])
            if isinstance(depends, list):
                for dep in depends:
                    if dep in enabled_set and dep != pid:
                        deps[pid].add(dep)
            required_caps_raw = manifest.get("required_capabilities", [])
            if not isinstance(required_caps_raw, list):
                continue
            for cap in (str(item) for item in required_caps_raw):
                capability = cap.strip()
                if not capability:
                    continue
                providers = [(provider_id, cast(CapabilityProxy, None)) for provider_id in provided_by_cap.get(capability, [])]
                if not providers:
                    continue
                policy = self._capability_policy(capability)
                providers = self._filtered_providers(capability, providers, policy)
                providers = self._ordered_providers(providers, policy)
                if policy.get("mode") == "multi":
                    max_providers = int(policy.get("max_providers", 0) or 0)
                    if max_providers > 0:
                        providers = providers[:max_providers]
                    provider_ids = [provider_id for provider_id, _proxy in providers]
                else:
                    provider_id, _proxy = self._resolve_single(capability, providers, policy)
                    provider_ids = [provider_id]
                for provider_id in provider_ids:
                    if provider_id != pid:
                        deps[pid].add(provider_id)

        remaining = {pid: set(items) for pid, items in deps.items()}
        order: list[str] = []
        ready = sorted(pid for pid, items in remaining.items() if not items)
        while ready:
            pid = ready.pop(0)
            order.append(pid)
            for other, items in remaining.items():
                if pid in items:
                    items.remove(pid)
                    if not items and other not in order and other not in ready:
                        ready.append(other)
            ready.sort()
        if len(order) != len(enabled_set):
            stuck = sorted(pid for pid, items in remaining.items() if items)
            raise PluginError(f"Plugin dependency cycle detected: {', '.join(stuck)}")
        return order

    def _plugin_overrides(self, plugin_id: str) -> dict[str, Any]:
        plugins_cfg = self.config.get("plugins", {}) if isinstance(self.config, dict) else {}
        settings = plugins_cfg.get("settings", {})
        if not isinstance(settings, dict):
            return {}
        overrides = settings.get(plugin_id, {})
        return overrides if isinstance(overrides, dict) else {}

    def _filesystem_policy(
        self,
        plugin_id: str,
        manifest: dict[str, Any],
        plugin_root: Path,
    ) -> FilesystemPolicy | None:
        perms = manifest.get("permissions", {}) if isinstance(manifest.get("permissions"), dict) else {}
        declared = manifest.get("filesystem_policy", {})
        config_policy = (
            self.config.get("plugins", {}).get("filesystem_policies", {}).get(plugin_id, {})
        )
        defaults = self.config.get("plugins", {}).get("filesystem_defaults", {})
        if not isinstance(defaults, dict):
            defaults = {}

        def _collect(raw: Any) -> list[str]:
            if not isinstance(raw, list):
                return []
            return [str(item) for item in raw if str(item).strip()]

        read_roots = []
        write_roots = []
        for source in (defaults, config_policy, declared):
            if isinstance(source, dict):
                read_roots.extend(_collect(source.get("read")))
                write_roots.extend(_collect(source.get("readwrite")))
        python_roots: list[str] = []
        try:
            paths = sysconfig.get_paths()
            for key in ("stdlib", "platstdlib", "purelib", "platlib"):
                path = paths.get(key)
                if path:
                    python_roots.append(str(path))
        except Exception:
            pass
        for root in (sys.prefix, getattr(sys, "base_prefix", None), getattr(sys, "exec_prefix", None)):
            if root:
                python_roots.append(str(root))
        try:
            python_roots.extend(site.getsitepackages())
        except Exception:
            pass
        try:
            user_site = site.getusersitepackages()
            if user_site:
                python_roots.append(str(user_site))
        except Exception:
            pass
        try:
            import zoneinfo

            for tz_path in getattr(zoneinfo, "TZPATH", ()):
                if tz_path:
                    python_roots.append(str(tz_path))
        except Exception:
            pass

        fs_perm = str(perms.get("filesystem", "none")).lower().strip() if isinstance(perms, dict) else "none"
        # Always allow read access to the plugin root for module resources.
        read_roots.append(str(plugin_root))
        if fs_perm == "none":
            read_roots = [str(plugin_root)]
            write_roots = []
        elif fs_perm == "read":
            write_roots = []
        elif fs_perm == "readwrite":
            pass
        read_roots.extend(python_roots)
        # Expand simple template variables.
        config = self.config if isinstance(self.config, dict) else {}
        data_dir = str(config.get("storage", {}).get("data_dir", "data"))
        plugins_cfg = config.get("plugins", {})
        hosting_cfg = plugins_cfg.get("hosting", {}) if isinstance(plugins_cfg, dict) else {}
        raw_cache_dir = hosting_cfg.get("cache_dir") if isinstance(hosting_cfg, dict) else None
        cache_dir = str(raw_cache_dir) if raw_cache_dir else str(Path(data_dir) / "cache" / "plugins")
        config_dir = str(config.get("paths", {}).get("config_dir", "config"))
        run_id = str(config.get("runtime", {}).get("run_id", "run"))
        run_dir = str(Path(data_dir) / "runs" / run_id)
        try:
            Path(run_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        metadata_db_path = str(config.get("storage", {}).get("metadata_path", "data/metadata.db"))
        media_dir = str(config.get("storage", {}).get("media_dir", "data/media"))
        audit_db_path = str(config.get("storage", {}).get("audit_db_path", "data/audit/kernel_audit.db"))
        spool_dir = str(config.get("storage", {}).get("spool_dir", "data/spool"))
        blob_dir = str(config.get("storage", {}).get("blob_dir", "data/blobs"))
        lexical_db_path = str(config.get("storage", {}).get("lexical_path", "data/lexical.db"))
        vector_db_path = str(config.get("storage", {}).get("vector_path", "data/vector.db"))
        state_tape_db_path = str(config.get("storage", {}).get("state_tape_path", "data/state/state_tape.db"))
        state_vector_db_path = str(config.get("storage", {}).get("state_vector_path", "data/state/state_vector.db"))

        if fs_perm in {"read", "readwrite"}:
            # Ensure every plugin has a narrow, deterministic scratch tmp dir for tempfiles.
            # This keeps OCR engines functional under the filesystem guard without granting
            # broad write access to /tmp.
            def _sanitize(pid: str) -> str:
                value = str(pid).strip() or "plugin"
                value = value.replace("\\", "_").replace("/", "_")
                return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in value)

            sanitized_id = _sanitize(plugin_id)
            plugin_cache_root = str(Path(cache_dir) / sanitized_id)
            plugin_tmp_dir = str(Path(plugin_cache_root) / "tmp")
            self._plugin_tmp_dirs[plugin_id] = plugin_tmp_dir
            read_roots.append(plugin_cache_root)
            write_roots.append(plugin_tmp_dir)
        anchor_path = ""
        anchor_dir = ""
        keyring_path = ""
        root_key_path = ""
        keyring_dir = ""
        root_key_dir = ""
        try:
            anchor_cfg = config.get("storage", {}).get("anchor", {})
            if isinstance(anchor_cfg, dict):
                raw_anchor_path = anchor_cfg.get("path")
                if isinstance(raw_anchor_path, str) and raw_anchor_path.strip():
                    anchor_path = raw_anchor_path
                    # Avoid filesystem-touching `resolve()` during boot; the filesystem
                    # guard performs realpath normalization at access time.
                    anchor_dir = str(Path(raw_anchor_path).expanduser().absolute().parent)
        except Exception:
            anchor_path = ""
            anchor_dir = ""
        try:
            crypto_cfg = config.get("storage", {}).get("crypto", {})
            if isinstance(crypto_cfg, dict):
                raw_keyring = crypto_cfg.get("keyring_path")
                if isinstance(raw_keyring, str) and raw_keyring.strip():
                    keyring_path = raw_keyring
                    try:
                        keyring_dir = str(Path(raw_keyring).expanduser().absolute().parent)
                    except Exception:
                        keyring_dir = ""
                raw_root = crypto_cfg.get("root_key_path")
                if isinstance(raw_root, str) and raw_root.strip():
                    root_key_path = raw_root
                    try:
                        root_key_dir = str(Path(raw_root).expanduser().absolute().parent)
                    except Exception:
                        root_key_dir = ""
        except Exception:
            keyring_path = ""
            root_key_path = ""
            keyring_dir = ""
            root_key_dir = ""
        repo_root = str(resolve_repo_path("."))
        mapping = {
            "data_dir": data_dir,
            "cache_dir": cache_dir,
            "config_dir": config_dir,
            "plugin_dir": str(plugin_root),
            "repo_root": repo_root,
            "run_dir": run_dir,
            "metadata_db_path": metadata_db_path,
            "media_dir": media_dir,
            "audit_db_path": audit_db_path,
            "spool_dir": spool_dir,
            "blob_dir": blob_dir,
            "lexical_db_path": lexical_db_path,
            "vector_db_path": vector_db_path,
            "state_tape_db_path": state_tape_db_path,
            "state_vector_db_path": state_vector_db_path,
            "anchor_path": anchor_path,
            "anchor_dir": anchor_dir,
            "keyring_path": keyring_path,
            "root_key_path": root_key_path,
            "keyring_dir": keyring_dir,
            "root_key_dir": root_key_dir,
        }

        def _expand(paths: list[str]) -> list[str]:
            expanded: list[str] = []
            for raw in paths:
                value = raw
                try:
                    value = value.format(**mapping)
                except Exception:
                    value = raw
                if str(value).strip():
                    expanded.append(value)
            return expanded

        read_roots = _expand(read_roots)
        write_roots = _expand(write_roots)
        if not read_roots and not write_roots:
            return None
        return FilesystemPolicy.from_paths(read=read_roots, readwrite=write_roots)

    def validate_allowlist_and_hashes(self, manifests: list[PluginManifest]) -> None:
        allowlist_raw = self.config.get("plugins", {}).get("allowlist", [])
        alias_map: dict[str, str] = {}
        for manifest in manifests:
            for old_id in manifest.replaces:
                old = str(old_id).strip()
                if old and old not in alias_map:
                    alias_map[old] = manifest.plugin_id
        allowlist = set(self._normalize_ids(allowlist_raw, alias_map))
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

    def _pair_allowed(self, a: str, b: str) -> bool:
        return _normalize_pair(a, b) in self._conflicts_allow_pairs

    def _declared_conflicts(self, manifest: dict[str, Any]) -> set[str]:
        conflicts = manifest.get("conflicts_with", [])
        replaces = manifest.get("replaces", [])
        out: set[str] = set()
        if isinstance(conflicts, list):
            out.update(str(pid).strip() for pid in conflicts if str(pid).strip())
        if isinstance(replaces, list):
            out.update(str(pid).strip() for pid in replaces if str(pid).strip())
        plugin_id = str(manifest.get("plugin_id", "")).strip()
        if plugin_id:
            out.discard(plugin_id)
        return out

    def _alias_map(self, manifests_by_id: dict[str, tuple[Path, dict[str, Any]]]) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        for plugin_id, (_, manifest) in manifests_by_id.items():
            replaces = manifest.get("replaces", [])
            if isinstance(replaces, list):
                for old_id in replaces:
                    old = str(old_id).strip()
                    if old and old not in alias_map:
                        alias_map[old] = plugin_id
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

    def _conflict_pairs(
        self,
        manifests_by_id: dict[str, tuple[Path, dict[str, Any]]],
        enabled_set: set[str],
    ) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        blocked: set[tuple[str, str]] = set()
        allowed: set[tuple[str, str]] = set()
        for plugin_id in sorted(enabled_set):
            manifest_entry = manifests_by_id.get(plugin_id)
            if manifest_entry is None:
                continue
            _path, manifest = manifest_entry
            for other in sorted(self._declared_conflicts(manifest)):
                if other not in enabled_set:
                    continue
                pair = _normalize_pair(plugin_id, other)
                if self._pair_allowed(*pair):
                    allowed.add(pair)
                else:
                    blocked.add(pair)
        return blocked, allowed

    def _check_conflicts(
        self,
        manifests_by_id: dict[str, tuple[Path, dict[str, Any]]],
        enabled_set: set[str],
    ) -> None:
        if not self._conflicts_enforce:
            return
        blocked, _allowed = self._conflict_pairs(manifests_by_id, enabled_set)
        if not blocked:
            return
        pairs = ", ".join(f"{a} <-> {b}" for a, b in sorted(blocked))
        raise PluginError(f"Plugin conflicts detected: {pairs}")

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
        failure_ordering = policy.get("failure_ordering", {})
        if not isinstance(failure_ordering, (dict, bool)):
            failure_ordering = {}
        policy["failure_ordering"] = failure_ordering
        try:
            policy["max_providers"] = int(policy.get("max_providers", 0))
        except Exception:
            policy["max_providers"] = 0
        policy["fanout"] = bool(policy.get("fanout", True))
        return policy

    def _failure_ordering_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        raw_global = self._failure_ordering_cfg
        if isinstance(raw_global, bool):
            settings["enabled"] = raw_global
        elif isinstance(raw_global, dict):
            settings.update(raw_global)
        raw_override = policy.get("failure_ordering")
        if isinstance(raw_override, bool):
            settings["enabled"] = raw_override
        elif isinstance(raw_override, dict):
            settings.update(raw_override)
        enabled = bool(settings.get("enabled", False))
        try:
            min_calls = int(settings.get("min_calls", 1) or 1)
        except Exception:
            min_calls = 1
        return {"enabled": enabled, "min_calls": max(1, min_calls)}

    def _ordered_providers(
        self,
        providers: list[tuple[str, CapabilityProxy]],
        policy: dict[str, Any],
    ) -> list[tuple[str, CapabilityProxy]]:
        base = sorted(providers, key=lambda item: item[0])
        failure_cfg = self._failure_ordering_policy(policy)
        if failure_cfg.get("enabled"):
            if self._failure_summary_cache is None:
                self._failure_summary_cache = self._audit_log.failure_summary()
            summary = self._failure_summary_cache
            min_calls = max(1, int(failure_cfg.get("min_calls", 1) or 1))

            def _score(item: tuple[str, CapabilityProxy]) -> tuple[int, int, int, str]:
                pid = item[0]
                stats = summary.get(pid, {})
                failures = int(stats.get("failures", 0) or 0)
                successes = int(stats.get("successes", 0) or 0)
                total = failures + successes
                if total < min_calls:
                    return (0, 0, 0, pid)
                rate_bp = int(round(10000 * failures / max(1, total)))
                return (rate_bp, failures, -successes, pid)

            base = sorted(base, key=_score)

        preferred = policy.get("preferred", [])
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
        # Deterministic fallback when multiple providers exist.
        return providers[0]

    def _resolve_capabilities(
        self,
        providers_by_cap: dict[str, list[tuple[str, CapabilityProxy]]],
    ) -> CapabilityRegistry:
        capabilities = CapabilityRegistry()
        for capability, providers in sorted(providers_by_cap.items(), key=lambda item: item[0]):
            policy = self._capability_policy(capability)
            providers = self._filtered_providers(capability, providers, policy)
            providers = self._ordered_providers(providers, policy)
            if policy.get("mode") == "multi":
                max_providers = int(policy.get("max_providers", 0) or 0)
                if max_providers > 0:
                    providers = providers[:max_providers]
                multi = MultiCapabilityProxy(capability, providers, policy)
                capabilities.register(capability, multi, network_allowed=False)
            else:
                if len(providers) == 1:
                    _plugin_id, proxy = providers[0]
                    capabilities.register(capability, proxy, network_allowed=proxy.network_allowed)
                else:
                    fallback = FallbackCapabilityProxy(capability, providers, policy)
                    capabilities.register(capability, fallback, network_allowed=False)
        return capabilities

    def _capabilities_for_plugins(self, plugins: list[LoadedPlugin]) -> CapabilityRegistry:
        providers_by_cap: dict[str, list[tuple[str, CapabilityProxy]]] = {}
        run_id = str(self.config.get("runtime", {}).get("run_id", "") or "run")
        for plugin in plugins:
            network_allowed = bool(plugin.manifest.get("permissions", {}).get("network", False))
            filesystem_policy = plugin.filesystem_policy
            plugin_root = plugin.manifest_path.parent if plugin.manifest_path is not None else resolve_repo_path(".")
            io_contracts = load_io_contracts(self._schema_registry, plugin.manifest, plugin_root=plugin_root)
            rng_seed_info = self._rng_service.seed_for_plugin(plugin.plugin_id) if self._rng_service.enabled else None
            rng_seed = rng_seed_info.plugin_seed if rng_seed_info else None
            for cap_name, impl in plugin.capabilities.items():
                # In-proc calls must be audited here. Subprocess-hosted plugins record audit rows
                # inside their subprocess host wrapper; avoid double-auditing RemoteCapability.
                audit_log = None
                try:
                    from .host import RemoteCapability  # local import to avoid cycles

                    if not isinstance(impl, RemoteCapability):
                        audit_log = self._audit_log
                except Exception:
                    audit_log = self._audit_log
                proxy = CapabilityProxy(
                    impl,
                    network_allowed,
                    filesystem_policy,
                    capability=cap_name,
                    io_contracts=io_contracts.get(cap_name, {}),
                    schema_registry=self._schema_registry,
                    rng_seed=rng_seed,
                    rng_strict=self._rng_service.strict,
                    rng_enabled=self._rng_service.enabled,
                    plugin_id=plugin.plugin_id,
                    trace_hook=self._trace.record,
                    audit_log=audit_log,
                    audit_run_id=run_id,
                )
                providers_by_cap.setdefault(cap_name, []).append((plugin.plugin_id, proxy))
        return self._resolve_capabilities(providers_by_cap)

    def _shutdown_instance(self, instance: Any) -> None:
        for method in ("stop", "close"):
            target = getattr(instance, method, None)
            if callable(target):
                try:
                    target()
                except Exception:
                    pass

    def hot_reload(
        self,
        current_plugins: list[LoadedPlugin],
        *,
        plugin_ids: list[str] | None = None,
    ) -> tuple[list[LoadedPlugin], CapabilityRegistry, dict[str, Any]]:
        clear_directory_hash_cache()
        new_plugins, _caps = self.load_plugins()
        load_report = self.load_report()
        failed = set(load_report.get("failed", [])) if isinstance(load_report, dict) else set()
        new_by_id = {plugin.plugin_id: plugin for plugin in new_plugins}
        current_by_id = {plugin.plugin_id: plugin for plugin in current_plugins}
        alias_map: dict[str, str] = {}
        for plugin in new_plugins:
            replaces = plugin.manifest.get("replaces", [])
            if isinstance(replaces, list):
                for old_id in replaces:
                    old = str(old_id).strip()
                    if old and old not in alias_map:
                        alias_map[old] = plugin.plugin_id

        hot_cfg = self.config.get("plugins", {}).get("hot_reload", {}) if isinstance(self.config, dict) else {}
        enabled = bool(hot_cfg.get("enabled", True)) if isinstance(hot_cfg, dict) else True
        if not enabled:
            raise PluginError("hot_reload_disabled")
        allowlist = set(self._normalize_ids(hot_cfg.get("allowlist", []), alias_map)) if isinstance(hot_cfg, dict) else set()
        blocklist = set(self._normalize_ids(hot_cfg.get("blocklist", []), alias_map)) if isinstance(hot_cfg, dict) else set()
        default_pack = set(self._normalize_ids(self.config.get("plugins", {}).get("default_pack", []), alias_map))
        inproc_allowlist = set(self._normalize_ids(self.config.get("plugins", {}).get("hosting", {}).get("inproc_allowlist", []), alias_map))
        blocklist |= default_pack
        blocklist |= inproc_allowlist

        requested = set(self._normalize_ids(plugin_ids or list(new_by_id.keys()), alias_map))
        failed_requested = sorted(pid for pid in requested if pid in failed)
        if failed_requested:
            raise PluginError(f"hot_reload_failed: {', '.join(failed_requested)}")
        blocked = sorted(pid for pid in requested if pid in blocklist)
        if allowlist:
            reload_ids = requested & allowlist
        else:
            reload_ids = requested - blocklist

        final_plugins: list[LoadedPlugin] = []
        reloaded: list[str] = []
        kept: list[str] = []
        added: list[str] = []
        removed: list[str] = []

        for plugin_id, new_plugin in new_by_id.items():
            if plugin_id in reload_ids or plugin_id not in current_by_id:
                if plugin_id in current_by_id and plugin_id in reload_ids:
                    self._shutdown_instance(current_by_id[plugin_id].instance)
                    reloaded.append(plugin_id)
                elif plugin_id not in current_by_id:
                    added.append(plugin_id)
                final_plugins.append(new_plugin)
            else:
                final_plugins.append(current_by_id[plugin_id])
                self._shutdown_instance(new_plugin.instance)
                kept.append(plugin_id)

        for plugin_id, plugin in current_by_id.items():
            if plugin_id not in new_by_id:
                self._shutdown_instance(plugin.instance)
                removed.append(plugin_id)

        capabilities = self._capabilities_for_plugins(final_plugins)
        report = {
            "reloaded": sorted(reloaded),
            "kept": sorted(kept),
            "added": sorted(added),
            "removed": sorted(removed),
            "blocked": blocked,
        }
        return final_plugins, capabilities, report

    def load_enabled(self, manifests: list[PluginManifest], *, safe_mode: bool) -> list[LoadedPlugin]:
        registry = self if safe_mode == self.safe_mode else PluginRegistry(self.config, safe_mode=safe_mode)
        loaded, _caps = registry.load_plugins()
        allowed_ids = {manifest.plugin_id for manifest in manifests}
        return [plugin for plugin in loaded if plugin.plugin_id in allowed_ids]

    def register_capabilities(self, plugins: list[Any], system: System) -> None:
        from autocapture_nx.kernel.system import System as SystemType

        if not isinstance(system, SystemType):
            raise PluginError("register_capabilities requires a System instance")
        run_id = str(self.config.get("runtime", {}).get("run_id", "") or "run")
        for plugin in plugins:
            if isinstance(plugin, LoadedPlugin):
                plugin_id = plugin.plugin_id
                caps = plugin.capabilities
                network_allowed = bool(plugin.manifest.get("permissions", {}).get("network", False))
                filesystem_policy = plugin.filesystem_policy
                plugin_root = plugin.manifest_path.parent if plugin.manifest_path is not None else resolve_repo_path(".")
                io_contracts = load_io_contracts(self._schema_registry, plugin.manifest, plugin_root=plugin_root)
                rng_seed_info = self._rng_service.seed_for_plugin(plugin.plugin_id) if self._rng_service.enabled else None
                rng_seed = rng_seed_info.plugin_seed if rng_seed_info else None
            elif hasattr(plugin, "capabilities"):
                plugin_id = str(getattr(plugin, "plugin_id", "unknown.plugin"))
                caps = plugin.capabilities()
                network_allowed = False
                filesystem_policy = None
                io_contracts = {}
                rng_seed = None
            else:
                continue
            for cap_name, impl in caps.items():
                policy = self._capability_policy(cap_name)
                audit_log = None
                try:
                    from .host import RemoteCapability  # local import to avoid cycles

                    if not isinstance(impl, RemoteCapability):
                        audit_log = self._audit_log
                except Exception:
                    audit_log = self._audit_log
                if system.has(cap_name):
                    if policy.get("mode") != "multi":
                        raise PluginError(f"Duplicate capability for {cap_name}: {plugin_id}")
                    existing = system.get(cap_name)
                    if isinstance(existing, CapabilityProxy):
                        existing = existing.target
                    if isinstance(existing, MultiCapabilityProxy):
                        existing.add_provider(
                            plugin_id,
                            CapabilityProxy(
                                impl,
                                network_allowed,
                                filesystem_policy,
                                capability=cap_name,
                                io_contracts=io_contracts.get(cap_name, {}),
                                schema_registry=self._schema_registry,
                                rng_seed=rng_seed,
                                rng_strict=self._rng_service.strict,
                                rng_enabled=self._rng_service.enabled,
                                plugin_id=plugin_id,
                                trace_hook=self._trace.record,
                                audit_log=audit_log,
                                audit_run_id=run_id,
                            ),
                        )
                        continue
                    raise PluginError(f"Existing capability for {cap_name} is not multi-capable")
                if policy.get("mode") == "multi":
                    multi = MultiCapabilityProxy(
                        cap_name,
                        [
                            (
                                plugin_id,
                                CapabilityProxy(
                                    impl,
                                    network_allowed,
                                    filesystem_policy,
                                    capability=cap_name,
                                    io_contracts=io_contracts.get(cap_name, {}),
                                    schema_registry=self._schema_registry,
                                    rng_seed=rng_seed,
                                    rng_strict=self._rng_service.strict,
                                    rng_enabled=self._rng_service.enabled,
                                    plugin_id=plugin_id,
                                    trace_hook=self._trace.record,
                                    audit_log=audit_log,
                                    audit_run_id=run_id,
                                ),
                            )
                        ],
                        policy,
                    )
                    system.register(cap_name, multi, network_allowed=False)
                else:
                    system.register(
                        cap_name,
                        CapabilityProxy(
                            impl,
                            network_allowed,
                            filesystem_policy,
                            capability=cap_name,
                            io_contracts=io_contracts.get(cap_name, {}),
                            schema_registry=self._schema_registry,
                            rng_seed=rng_seed,
                            rng_strict=self._rng_service.strict,
                            rng_enabled=self._rng_service.enabled,
                            plugin_id=plugin_id,
                            trace_hook=self._trace.record,
                            audit_log=audit_log,
                            audit_run_id=run_id,
                        ),
                        network_allowed=network_allowed,
                        filesystem_policy=filesystem_policy,
                    )

    def load_plugins(self) -> tuple[list[LoadedPlugin], CapabilityRegistry]:
        self._load_report = {"loaded": [], "failed": [], "skipped": [], "errors": []}
        self._failure_summary_cache = None
        manifests = self.discover_manifest_paths()
        lockfile = self.load_lockfile()
        plugins_cfg = self.config.get("plugins", {}) if isinstance(self.config, dict) else {}
        safe_mode_minimal = bool(plugins_cfg.get("safe_mode_minimal", False))
        if os.getenv("AUTOCAPTURE_SAFE_MODE_MINIMAL", "").lower() in {"1", "true", "yes"}:
            safe_mode_minimal = True
        hosting_cfg = self.config.get("plugins", {}).get("hosting", {})
        hosting_mode = str(hosting_cfg.get("mode", "subprocess")).lower()
        # Tests and low-resource environments (WSL) may need to force inproc hosting
        # to avoid spawning many subprocess plugin hosts and exhausting RAM.
        hosting_mode_env = os.getenv("AUTOCAPTURE_PLUGINS_HOSTING_MODE", "").strip().lower()
        if hosting_mode_env:
            hosting_mode = hosting_mode_env
        if hosting_mode not in {"subprocess", "inproc"}:
            raise PluginError(f"Unsupported plugin hosting mode: {hosting_mode}")
        # Safe-mode minimal is used by perf/health gates; avoid paying the subprocess startup tax.
        if self.safe_mode and safe_mode_minimal:
            hosting_mode = "inproc"
        # WSL2 is often memory-constrained; subprocess hosting can spawn many heavy
        # Python processes (one per plugin) and destabilize the VM. Default to
        # in-proc hosting on WSL unless explicitly overridden by env or by setting
        # hosting.wsl_force_inproc=false.
        wsl_force_inproc = bool(hosting_cfg.get("wsl_force_inproc", True))
        if (
            hosting_mode_env == ""
            and hosting_mode == "subprocess"
            and wsl_force_inproc
            and _is_wsl()
        ):
            hosting_mode = "inproc"

        manifests_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
        for manifest_path in manifests:
            manifest: dict[str, Any] | None = None
            try:
                with manifest_path.open("r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
                self._validate_manifest(manifest)
                self._check_compat(manifest)
                plugin_id = manifest["plugin_id"]
            except Exception as exc:
                self._record_load_failure(
                    plugin_id=str(manifest.get("plugin_id")) if isinstance(manifest, dict) else None,
                    entrypoint=str(manifest_path),
                    phase="manifest",
                    error=str(exc),
                )
                continue
            manifests_by_id[plugin_id] = (manifest_path, manifest)

        alias_map = self._alias_map(manifests_by_id)
        allowlist = set(self._normalize_ids(self.config.get("plugins", {}).get("allowlist", []), alias_map))
        enabled_map = self._normalize_enabled_map(self.config.get("plugins", {}).get("enabled", {}), alias_map)
        default_pack = set(self._normalize_ids(self.config.get("plugins", {}).get("default_pack", []), alias_map))
        inproc_allowlist = set(self._normalize_ids(hosting_cfg.get("inproc_allowlist", []), alias_map))
        self._validate_inproc_justifications(inproc_allowlist)
        quarantine_cfg = plugins_cfg.get("quarantine", {}) if isinstance(plugins_cfg, dict) else {}
        quarantine_ids: set[str] = set()
        if isinstance(quarantine_cfg, dict):
            quarantine_ids = set(self._normalize_ids(list(quarantine_cfg.keys()), alias_map))
        elif isinstance(quarantine_cfg, list):
            quarantine_ids = set(self._normalize_ids(quarantine_cfg, alias_map))

        # Never quarantine core storage/ledger/anchor providers; quarantining them
        # can make the kernel unbootable (missing required capabilities).
        core_caps = {"storage.metadata", "storage.media", "journal.writer", "ledger.writer", "anchor.writer"}

        def _is_core_plugin(pid: str) -> bool:
            entry = manifests_by_id.get(pid)
            if not entry:
                return False
            _path, manifest = entry
            provides = manifest.get("provides", []) if isinstance(manifest, dict) else []
            if not isinstance(provides, list):
                return False
            for cap in provides:
                if str(cap).strip() in core_caps:
                    return True
            return False

        quarantine_ids = {pid for pid in quarantine_ids if not _is_core_plugin(pid)}
        # EXT-07: inproc must be explicitly allowlisted. On WSL we auto-fill the
        # allowlist with enabled plugins to avoid subprocess OOM while keeping a
        # deterministic, inspectable allowlist.
        effective_inproc_allowlist: set[str] = set(inproc_allowlist)
        allow_all_inproc = bool(hosting_cfg.get("inproc_allow_all", False))
        # Safe-mode minimal is used by health/perf gates; it must not fail open
        # due to missing allowlist plumbing. In safe-mode minimal, we allow
        # in-proc loading of the minimal pack deterministically.
        if self.safe_mode and safe_mode_minimal:
            allow_all_inproc = True

        def use_inproc(pid: str) -> bool:
            if hosting_mode == "inproc":
                if allow_all_inproc:
                    return True
                return pid in effective_inproc_allowlist
            return pid in effective_inproc_allowlist

        loaded: list[LoadedPlugin] = []
        capabilities = CapabilityRegistry()
        providers_by_cap: dict[str, list[tuple[str, CapabilityProxy]]] = {}
        failed_ids: set[str] = set()
        skipped_ids: set[str] = set()
        loaded_ids: set[str] = set()

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
        if quarantine_ids:
            enabled_set = {pid for pid in enabled_set if pid not in quarantine_ids}
        # WSL2 stability: when running in-proc (whether auto-forced or explicitly
        # requested via env/config), default the effective inproc allowlist to the
        # enabled set if no allowlist was provided. This preserves EXT-07's
        # "explicit inproc allowlist" invariant without requiring test harnesses
        # to plumb per-plugin justifications for ephemeral local plugins.
        if hosting_mode == "inproc" and _is_wsl() and not effective_inproc_allowlist:
            # Only auto-fill the in-proc allowlist when WSL in-proc hosting is
            # being forced/enabled by policy. Tests may explicitly disable
            # this behavior to validate EXT-07 fail-closed semantics.
            if wsl_force_inproc:
                effective_inproc_allowlist.update(sorted(enabled_set))

        # EXT-08: crash-loop containment (auto-quarantine repeated failures).
        # Best-effort and deterministic: quarantine only when failures exceed a
        # fixed threshold within a bounded window.
        try:
            health_cfg = plugins_cfg.get("health", {}) if isinstance(plugins_cfg, dict) else {}
            auto_quarantine = bool(health_cfg.get("auto_quarantine", True))
            crash_limit = int(health_cfg.get("crash_loop_failures", 3) or 3)
            crash_window_s = int(health_cfg.get("crash_loop_window_s", 300) or 300)
        except Exception:
            auto_quarantine = True
            crash_limit = 3
            crash_window_s = 300
        if auto_quarantine and crash_limit > 0 and crash_window_s > 0 and enabled_set:
            # Load current user quarantine map so we can persist new quarantines.
            from autocapture_nx.kernel.atomic_write import atomic_write_json
            from datetime import datetime, timezone

            config_dir = self.config.get("paths", {}).get("config_dir", "config") if isinstance(self.config, dict) else "config"
            user_path = Path(str(config_dir)) / "user.json"
            try:
                user_cfg = json.loads(user_path.read_text(encoding="utf-8")) if user_path.exists() else {}
            except Exception:
                user_cfg = {}
            user_plugins = user_cfg.setdefault("plugins", {}) if isinstance(user_cfg, dict) else {}
            user_quarantine = user_plugins.setdefault("quarantine", {}) if isinstance(user_plugins, dict) else {}
            if not isinstance(user_quarantine, dict):
                user_quarantine = {}
                if isinstance(user_plugins, dict):
                    user_plugins["quarantine"] = user_quarantine
            new_quarantines: list[str] = []
            removed_quarantines: list[str] = []
            for pid in sorted(enabled_set):
                if _is_core_plugin(pid):
                    # Ensure stale quarantine entries do not disable core plugins.
                    try:
                        if isinstance(user_quarantine, dict) and pid in user_quarantine:
                            user_quarantine.pop(pid, None)
                            removed_quarantines.append(pid)
                    except Exception:
                        pass
                    quarantine_ids.discard(pid)
                    continue
                if pid in quarantine_ids or pid in user_quarantine:
                    continue
                try:
                    recent = self._audit_log.recent_failures(pid, window_s=crash_window_s)
                except Exception:
                    continue
                if not (isinstance(recent, dict) and recent.get("ok")):
                    continue
                try:
                    failures = int(recent.get("failures") or 0)
                except Exception:
                    failures = 0
                if failures >= crash_limit:
                    quarantine_ids.add(pid)
                    new_quarantines.append(pid)
                    user_quarantine[pid] = {
                        "reason": "crash_loop",
                        "failures": failures,
                        "window_s": int(crash_window_s),
                        "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    }
            if new_quarantines or removed_quarantines:
                # Persist quarantine marks; do not delete old entries.
                try:
                    atomic_write_json(user_path, user_cfg, sort_keys=True, indent=2)
                except Exception:
                    pass
            if new_quarantines:
                enabled_set = {pid for pid in enabled_set if pid not in quarantine_ids}

        if (self.safe_mode or plugins_cfg.get("safe_mode", False)) and safe_mode_minimal:
            minimal = self._minimal_safe_mode_set(manifests_by_id, allowlist, alias_map)
            if minimal:
                enabled_set = minimal

        self._check_conflicts(manifests_by_id, enabled_set)

        load_order = self._plugin_load_order(manifests_by_id, enabled_set)
        for plugin_id in load_order:
            manifest_path, manifest = manifests_by_id[plugin_id]
            if plugin_id not in allowlist:
                continue
            if plugin_id not in enabled_set:
                continue
            depends = manifest.get("depends_on", [])
            blocked = False
            for dep in depends:
                if dep in failed_ids:
                    self._record_load_failure(
                        plugin_id=plugin_id,
                        entrypoint=str(manifest_path),
                        phase="dependency",
                        error=f"depends on failed plugin {dep}",
                    )
                    blocked = True
                    continue
                if dep not in allowlist:
                    self._record_load_failure(
                        plugin_id=plugin_id,
                        entrypoint=str(manifest_path),
                        phase="dependency",
                        error=f"depends on non-allowlisted {dep}",
                    )
                    blocked = True
                    continue
                if dep not in enabled_set:
                    self._record_load_failure(
                        plugin_id=plugin_id,
                        entrypoint=str(manifest_path),
                        phase="dependency",
                        error=f"depends on disabled {dep}",
                    )
                    blocked = True
            if blocked:
                skipped_ids.add(plugin_id)
                continue
            local_loaded: list[LoadedPlugin] = []
            local_providers: dict[str, list[tuple[str, CapabilityProxy]]] = {}
            try:
                self._check_permissions(manifest)
                self._check_lock(plugin_id, manifest_path, manifest_path.parent, lockfile)

                entrypoints = manifest.get("entrypoints", [])
                if not entrypoints:
                    raise PluginError(f"Plugin {plugin_id} has no entrypoints")
                if "required_capabilities" not in manifest:
                    raise PluginError(f"Plugin {plugin_id} missing required_capabilities")
                required_caps_raw = manifest.get("required_capabilities", [])
                if not isinstance(required_caps_raw, list):
                    raise PluginError(f"Plugin {plugin_id} required_capabilities must be a list")
                required_capabilities = {str(cap) for cap in required_caps_raw if str(cap).strip()}
                settings_paths = manifest.get("settings_paths", []) or []
                if not isinstance(settings_paths, list):
                    settings_paths = []
                default_settings = manifest.get("default_settings") if isinstance(manifest.get("default_settings"), dict) else None
                plugin_settings = build_plugin_settings(
                    self.config,
                    settings_paths=[str(path) for path in settings_paths if str(path).strip()],
                    default_settings=default_settings,
                    overrides=self._plugin_overrides(plugin_id),
                )
                try:
                    settings_schema = self._resolve_settings_schema(
                        manifest,
                        plugin_root=manifest_path.parent,
                        settings_paths=[str(path) for path in settings_paths if str(path).strip()],
                    )
                except ValueError as exc:
                    raise PluginError(f"Plugin {plugin_id} settings schema error: {exc}") from exc
                self._validate_settings_schema(
                    plugin_id=plugin_id,
                    schema=settings_schema,
                    settings=plugin_settings,
                )
                settings_hash, _ = hash_payload(plugin_settings)
                io_contracts = load_io_contracts(
                    self._schema_registry,
                    manifest,
                    plugin_root=manifest_path.parent,
                )
                rng_seed_info = self._rng_service.seed_for_plugin(plugin_id) if self._rng_service.enabled else None
                rng_seed = rng_seed_info.plugin_seed if rng_seed_info else None
                rng_seed_hex = rng_seed_info.seed_hex if rng_seed_info else None
                code_hash = self._compute_code_hash(
                    manifest_path=manifest_path,
                    plugin_root=manifest_path.parent,
                    entrypoints=entrypoints,
                    manifest=manifest,
                )
                network_requested = bool(manifest.get("permissions", {}).get("network", False))
                network_scope = self._network_scope_for_plugin(plugin_id, network_requested=network_requested)
                network_allowed = network_scope != "none"
                filesystem_policy = self._filesystem_policy(plugin_id, manifest, manifest_path.parent)

                inproc = use_inproc(plugin_id)
                if hosting_mode == "inproc" and not allow_all_inproc and not inproc:
                    raise PluginError(f"inproc_not_allowlisted:{plugin_id}")
                for entry in entrypoints:
                    module_path = manifest_path.parent / entry["path"]
                    if not module_path.exists():
                        raise PluginError(f"Missing entrypoint module {module_path}")
                    if inproc:
                        instance = self._load_inproc_instance(
                            module_path=module_path,
                            callable_name=entry["callable"],
                            plugin_id=plugin_id,
                            plugin_settings=plugin_settings,
                            required_capabilities=required_capabilities,
                            capabilities=capabilities,
                            network_allowed=network_allowed,
                            filesystem_policy=filesystem_policy,
                            rng_seed=rng_seed,
                            rng_seed_hex=rng_seed_hex,
                        )
                    else:
                        provides = manifest.get("provides", [])
                        if not isinstance(provides, list):
                            provides = []
                        instance = SubprocessPlugin(
                            module_path,
                            entry["callable"],
                            plugin_id,
                            network_scope,
                            self.config,
                            plugin_config=plugin_settings,
                            capabilities=capabilities,
                            allowed_capabilities=required_capabilities,
                            filesystem_policy=filesystem_policy.payload() if filesystem_policy else None,
                            entrypoint_kind=str(entry.get("kind", "")).strip() or None,
                            provided_capabilities=[str(item) for item in provides if str(item).strip()],
                            rng_seed=rng_seed,
                            rng_seed_hex=rng_seed_hex,
                            rng_strict=self._rng_service.strict,
                            rng_enabled=self._rng_service.enabled,
                            audit_log=self._audit_log,
                            code_hash=code_hash,
                            settings_hash=settings_hash,
                        )
                    try:
                        caps = instance.capabilities()
                    except Exception:
                        self._shutdown_instance(instance)
                        raise
                    # WSL stability: if we had to spin up a subprocess host just to
                    # enumerate capabilities at boot, close it immediately. The
                    # SubprocessPlugin will restart lazily on first real use.
                    try:
                        if bool(getattr(instance, "_capabilities_probe_only", False)):
                            instance.close()
                    except Exception:
                        pass
                    if isinstance(caps, dict):
                        manifest_provides = manifest.get("provides", [])
                        if isinstance(manifest_provides, list) and caps:
                            fallback_impl = next(iter(caps.values()))
                            for cap in manifest_provides:
                                cap_name = str(cap).strip()
                                if cap_name and cap_name not in caps:
                                    caps[cap_name] = fallback_impl
                    audit_run_id = str(self.config.get("runtime", {}).get("run_id", "") or "run")
                    for cap_name, impl in caps.items():
                        audit_log = None
                        try:
                            from .host import RemoteCapability  # local import to avoid cycles

                            if not isinstance(impl, RemoteCapability):
                                audit_log = self._audit_log
                        except Exception:
                            audit_log = self._audit_log
                        proxy = CapabilityProxy(
                            impl,
                            network_allowed,
                            filesystem_policy,
                            capability=cap_name,
                            io_contracts=io_contracts.get(cap_name, {}),
                            schema_registry=self._schema_registry,
                            rng_seed=rng_seed,
                            rng_strict=self._rng_service.strict,
                            rng_enabled=self._rng_service.enabled,
                            plugin_id=plugin_id,
                            trace_hook=self._trace.record,
                            audit_log=audit_log,
                            audit_run_id=audit_run_id,
                            audit_code_hash=code_hash,
                            audit_settings_hash=settings_hash,
                            temp_dir=self._plugin_tmp_dirs.get(plugin_id),
                        )
                        local_providers.setdefault(cap_name, []).append((plugin_id, proxy))
                    local_loaded.append(LoadedPlugin(plugin_id, manifest, instance, caps, filesystem_policy, manifest_path))

                for cap_name, items in local_providers.items():
                    providers_by_cap.setdefault(cap_name, []).extend(items)
                loaded.extend(local_loaded)
                loaded_ids.add(plugin_id)
                try:
                    self._audit_log.record_plugin_metadata(
                        plugin_id=plugin_id,
                        version=str(manifest.get("version", "")) if manifest else None,
                        code_hash=code_hash,
                        settings_hash=settings_hash,
                        capability_tags=_normalize_tags(manifest.get("capability_tags")),
                        provides=[str(item) for item in manifest.get("provides", []) if str(item).strip()],
                        entrypoints=[
                            {
                                "kind": str(entry.get("kind", "")),
                                "id": str(entry.get("id", "")),
                                "path": str(entry.get("path", "")),
                                "callable": str(entry.get("callable", "")),
                            }
                            for entry in entrypoints
                        ],
                        permissions=dict(manifest.get("permissions", {})) if isinstance(manifest.get("permissions"), dict) else None,
                        manifest_path=str(manifest_path),
                    )
                except Exception:
                    pass
                resolved = self._resolve_capabilities(providers_by_cap)
                capabilities.replace_all(resolved.all())
            except Exception as exc:
                for loaded_plugin in local_loaded:
                    self._shutdown_instance(loaded_plugin.instance)
                failed_ids.add(plugin_id)
                self._record_load_failure(
                    plugin_id=plugin_id,
                    entrypoint=str(manifest_path),
                    phase="load",
                    error=str(exc),
                )
                continue

        resolved = self._resolve_capabilities(providers_by_cap)
        capabilities.replace_all(resolved.all())
        for err in self._load_report.get("errors", []):
            plugin_id = err.get("plugin_id") if isinstance(err, dict) else None
            if plugin_id:
                failed_ids.add(str(plugin_id))
        self._load_report["loaded"] = sorted(loaded_ids)
        self._load_report["failed"] = sorted(failed_ids)
        self._load_report["skipped"] = sorted(skipped_ids)
        try:
            capabilities.register("observability.plugin_trace", self._trace, network_allowed=False)
            capabilities.register("observability.plugin_load_report", self._load_reporter, network_allowed=False)
        except Exception:
            pass
        return loaded, capabilities
