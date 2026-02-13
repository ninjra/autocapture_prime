"""NX plugin manager for discovery and policy settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.audit import PluginAuditLog
from autocapture_nx.kernel.atomic_write import atomic_write_json
from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.paths import resolve_repo_path

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
    kinds: List[str]
    provides: List[str]
    capability_tags: List[str]
    permissions: Dict[str, Any]
    depends_on: List[str]
    conflicts_with: List[str]
    conflicts_active: List[str]
    conflicts_allowed: List[str]
    conflicts_blocked: List[str]
    conflicts_enforced: bool
    conflict_ok: bool
    failure_history: Dict[str, Any]


class PluginManager:
    def __init__(self, config: dict[str, Any], safe_mode: bool = False) -> None:
        self.config = config
        self.safe_mode = safe_mode
        self._registry = PluginRegistry(config, safe_mode=safe_mode)
        self._validator = SchemaLiteValidator()

    def _now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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
        atomic_write_json(path, payload, sort_keys=True, indent=2)

    def _lockfile_path(self) -> Path:
        locks_cfg = self.config.get("plugins", {}).get("locks", {}) if isinstance(self.config, dict) else {}
        raw = locks_cfg.get("lockfile", "config/plugin_locks.json")
        return resolve_repo_path(str(raw))

    def _lockfile_history_dir(self) -> Path:
        lockfile = self._lockfile_path()
        return lockfile.parent / "plugin_locks.history"

    def _read_lockfile(self) -> dict[str, Any]:
        lockfile = self._lockfile_path()
        if not lockfile.exists():
            return {}
        return json.loads(lockfile.read_text(encoding="utf-8"))

    def _write_lockfile(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self._lockfile_path(), payload, sort_keys=True, indent=2)

    def lockfile_snapshot(self, *, reason: str) -> dict[str, Any]:
        """Archive the current lockfile (append-only history; no deletion)."""
        lockfile = self._lockfile_path()
        if not lockfile.exists():
            return {"ok": False, "error": "lockfile_missing", "lockfile": str(lockfile)}
        history = self._lockfile_history_dir()
        history.mkdir(parents=True, exist_ok=True)
        ts = self._now_utc().replace(":", "").replace("-", "")
        sha = sha256_file(lockfile)[:12]
        dest = history / f"{ts}_{str(reason).strip() or 'snapshot'}_{sha}.json"
        dest.write_text(lockfile.read_text(encoding="utf-8"), encoding="utf-8")
        return {"ok": True, "snapshot": str(dest), "sha256": sha256_file(dest)}

    def lockfile_rollback(self, snapshot_path: str) -> dict[str, Any]:
        """Rollback lockfile to a previous snapshot (archive/migrate only)."""
        src = resolve_repo_path(snapshot_path)
        if not src.exists():
            return {"ok": False, "error": "snapshot_missing", "snapshot": str(src)}
        self.lockfile_snapshot(reason="pre_rollback")
        self._write_lockfile(json.loads(src.read_text(encoding="utf-8")))
        return {"ok": True, "lockfile": str(self._lockfile_path()), "restored_from": str(src)}

    def lockfile_diff(self, a_path: str, b_path: str) -> dict[str, Any]:
        """EXT-03: stable diff between two lockfile snapshots."""
        a = resolve_repo_path(a_path)
        b = resolve_repo_path(b_path)
        if not a.exists() or not b.exists():
            return {
                "ok": False,
                "error": "snapshot_missing",
                "a": str(a),
                "b": str(b),
                "a_exists": a.exists(),
                "b_exists": b.exists(),
            }
        try:
            a_obj = json.loads(a.read_text(encoding="utf-8"))
        except Exception:
            a_obj = {}
        try:
            b_obj = json.loads(b.read_text(encoding="utf-8"))
        except Exception:
            b_obj = {}
        a_plugins = a_obj.get("plugins", {}) if isinstance(a_obj, dict) else {}
        b_plugins = b_obj.get("plugins", {}) if isinstance(b_obj, dict) else {}
        if not isinstance(a_plugins, dict):
            a_plugins = {}
        if not isinstance(b_plugins, dict):
            b_plugins = {}
        keys = sorted({*a_plugins.keys(), *b_plugins.keys()}, key=lambda k: str(k))
        changes: list[dict[str, Any]] = []
        for pid in keys:
            before = a_plugins.get(pid)
            after = b_plugins.get(pid)
            if before == after:
                continue
            changes.append({"plugin_id": str(pid), "before": before, "after": after})
        return {
            "ok": True,
            "a": str(a),
            "b": str(b),
            "changes": changes,
            "changes_count": int(len(changes)),
        }

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
        merged_cfg = deep_merge(self.config, self._load_user_config())
        plugins_cfg = merged_cfg.get("plugins", {}) if isinstance(merged_cfg, dict) else {}
        allowlist = set(self._normalize_ids(plugins_cfg.get("allowlist", []), alias_map))
        enabled_map = self._normalize_enabled_map(plugins_cfg.get("enabled", {}), alias_map)
        default_pack = set(self._normalize_ids(plugins_cfg.get("default_pack", []), alias_map))
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
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.get("plugins", {}) if isinstance(user_cfg, dict) else {}
        approvals = plugins_cfg.get("approvals", {}) if isinstance(plugins_cfg, dict) else {}
        quarantine = plugins_cfg.get("quarantine", {}) if isinstance(plugins_cfg, dict) else {}
        if not isinstance(approvals, dict):
            approvals = {}
        if not isinstance(quarantine, dict):
            quarantine = {}
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        lockfile = self._registry.load_lockfile() if locks_cfg.get("enforce", True) else {"plugins": {}}
        plugin_locks = lockfile.get("plugins", {})
        failure_summary: dict[str, dict[str, Any]] = {}
        try:
            failure_summary = PluginAuditLog.from_config(self.config).failure_summary()
        except Exception:
            failure_summary = {}
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
                    enabled=(manifest.plugin_id in enabled_ids and manifest.plugin_id not in quarantine),
                    allowlisted=manifest.plugin_id in allowlist,
                    hash_ok=hash_ok,
                    version=manifest.version,
                    kinds=sorted({entry.kind for entry in manifest.entrypoints if entry.kind}),
                    provides=sorted({str(item) for item in (manifest.provides or []) if str(item).strip()}),
                    capability_tags=sorted({str(item) for item in (getattr(manifest, "capability_tags", []) or []) if str(item).strip()}),
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
                    failure_history={
                        **(failure_summary.get(manifest.plugin_id, {}) or {}),
                        "approved": bool(manifest.plugin_id in approvals),
                        "quarantined": bool(manifest.plugin_id in quarantine),
                    },
                )
            )
        return sorted(rows, key=lambda r: r.plugin_id)

    def lifecycle_state(self, plugin_id: str) -> dict[str, Any]:
        """EXT-01: compute a stable lifecycle state for a plugin."""
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        manifest = self._manifest_for(plugin_id, manifests)
        if manifest is None:
            return {"ok": False, "error": "plugin_not_found", "plugin_id": plugin_id}
        lockfile = self._registry.load_lockfile()
        locks = lockfile.get("plugins", {}) if isinstance(lockfile, dict) else {}
        locked = bool(isinstance(locks, dict) and plugin_id in locks)
        hash_ok = True
        if locked:
            try:
                expected = locks.get(plugin_id, {}) if isinstance(locks, dict) else {}
                hash_ok = (
                    sha256_file(manifest.path) == expected.get("manifest_sha256")
                    and sha256_directory(manifest.path.parent) == expected.get("artifact_sha256")
                )
            except Exception:
                hash_ok = False
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.get("plugins", {}) if isinstance(user_cfg, dict) else {}
        approvals = plugins_cfg.get("approvals", {}) if isinstance(plugins_cfg, dict) else {}
        quarantine = plugins_cfg.get("quarantine", {}) if isinstance(plugins_cfg, dict) else {}
        approved = bool(isinstance(approvals, dict) and plugin_id in approvals)
        quarantined = bool(isinstance(quarantine, dict) and plugin_id in quarantine)
        enabled = bool(plugin_id in self._enabled_plugin_ids(manifests) and not quarantined)
        failures = 0
        try:
            failures = int((PluginAuditLog.from_config(self.config).failure_summary().get(plugin_id, {}) or {}).get("failures", 0) or 0)
        except Exception:
            failures = 0
        healthy = bool(enabled and failures == 0 and hash_ok)
        if quarantined:
            state = "quarantined"
        elif healthy:
            state = "healthy"
        elif enabled:
            state = "enabled"
        elif approved:
            state = "approved"
        elif locked and hash_ok:
            state = "locked"
        else:
            state = "installed"
        return {
            "ok": True,
            "plugin_id": plugin_id,
            "state": state,
            "installed": True,
            "locked": locked,
            "hash_ok": bool(hash_ok),
            "approved": approved,
            "enabled": enabled,
            "healthy": healthy,
            "quarantined": quarantined,
        }

    def permissions_digest(self, plugin_id: str) -> dict[str, Any]:
        """EXT-06: stable permission digest used for explicit approvals."""
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        manifest = self._manifest_for(plugin_id, manifests)
        if manifest is None:
            return {"ok": False, "error": "plugin_not_found", "plugin_id": plugin_id}
        declared_fs = manifest.filesystem_policy if isinstance(manifest.filesystem_policy, dict) else {}
        payload = {
            "filesystem": manifest.permissions.filesystem,
            "filesystem_policy": declared_fs,
            "gpu": bool(manifest.permissions.gpu),
            "raw_input": bool(manifest.permissions.raw_input),
            "network": bool(manifest.permissions.network),
        }
        digest = sha256_text(canonical_dumps(payload))
        return {"ok": True, "plugin_id": plugin_id, "digest": digest, "permissions": payload}

    def approve_permissions(self, plugin_id: str, *, accept_digest: str) -> dict[str, Any]:
        return self.approve_permissions_confirm(plugin_id, accept_digest=str(accept_digest), confirm="")

    def approve_permissions_confirm(self, plugin_id: str, *, accept_digest: str, confirm: str) -> dict[str, Any]:
        """EXT-06: explicit approvals w/ high-risk confirmation."""
        report = self.permissions_digest(plugin_id)
        if not report.get("ok", False):
            return report
        expected = str(report.get("digest") or "")
        got = str(accept_digest or "").strip()
        if got != expected:
            return {"ok": False, "error": "digest_mismatch", "expected": expected, "got": got}
        perms_raw = report.get("permissions")
        perms: dict[str, Any] = perms_raw if isinstance(perms_raw, dict) else {}
        high_risk = bool(perms.get("network")) or bool(perms.get("filesystem"))
        if high_risk:
            required = f"APPROVE:{report['plugin_id']}"
            if str(confirm or "").strip() != required:
                return {"ok": False, "error": "confirmation_required", "required": required, "high_risk": True}
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        approvals = plugins_cfg.setdefault("approvals", {})
        if not isinstance(approvals, dict):
            approvals = {}
            plugins_cfg["approvals"] = approvals
        approvals[str(report["plugin_id"])] = {"digest": expected, "ts_utc": self._now_utc(), "permissions": perms}
        self._write_user_config(user_cfg)
        return {"ok": True, "plugin_id": str(report["plugin_id"]), "digest": expected, "high_risk": high_risk}

    def quarantine(self, plugin_id: str, *, reason: str) -> dict[str, Any]:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        quarantine = plugins_cfg.setdefault("quarantine", {})
        if not isinstance(quarantine, dict):
            quarantine = {}
            plugins_cfg["quarantine"] = quarantine
        quarantine[plugin_id] = {"reason": str(reason), "ts_utc": self._now_utc()}
        self._write_user_config(user_cfg)
        return {"ok": True, "plugin_id": plugin_id, "quarantined": True}

    def unquarantine(self, plugin_id: str) -> dict[str, Any]:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.get("plugins", {}) if isinstance(user_cfg, dict) else {}
        quarantine = plugins_cfg.get("quarantine", {}) if isinstance(plugins_cfg, dict) else {}
        if isinstance(quarantine, dict):
            quarantine.pop(plugin_id, None)
        self._write_user_config(user_cfg)
        return {"ok": True, "plugin_id": plugin_id, "quarantined": False}

    def enable(self, plugin_id: str) -> None:
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        approvals_required = bool(self.config.get("plugins", {}).get("approvals", {}).get("required", False))
        if approvals_required:
            user_cfg = self._load_user_config()
            plugins_cfg = user_cfg.get("plugins", {}) if isinstance(user_cfg, dict) else {}
            approvals = plugins_cfg.get("approvals", {}) if isinstance(plugins_cfg, dict) else {}
            if not (isinstance(approvals, dict) and plugin_id in approvals):
                raise RuntimeError(f"plugin_not_approved:{plugin_id}")
        locks_cfg = self.config.get("plugins", {}).get("locks", {})
        if bool(locks_cfg.get("enforce", True)):
            lockfile = self._registry.load_lockfile()
            locks = lockfile.get("plugins", {}) if isinstance(lockfile, dict) else {}
            if not (isinstance(locks, dict) and plugin_id in locks):
                raise RuntimeError(f"plugin_not_locked:{plugin_id}")
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        allowlist = plugins_cfg.setdefault("allowlist", [])
        if not isinstance(allowlist, list):
            allowlist = []
            plugins_cfg["allowlist"] = allowlist
        if plugin_id not in [str(item) for item in allowlist]:
            allowlist.append(plugin_id)
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

    def install_local(self, path: str, *, dry_run: bool = True) -> Dict[str, Any]:
        """EXT-02: local-only plugin install with manifest validation and lock preview."""
        root = resolve_repo_path(path)
        if root.is_file():
            root = root.parent
        manifest_path = root / "plugin.json"
        if not manifest_path.exists():
            return {"ok": False, "error": "manifest_missing", "path": str(root)}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Use the registry's validator to stay aligned with the manifest schema.
        self._registry._validate_manifest(manifest)  # noqa: SLF001
        self._registry._check_compat(manifest)  # noqa: SLF001
        plugin_id = str(manifest.get("plugin_id") or "")
        if not plugin_id:
            return {"ok": False, "error": "plugin_id_missing"}

        lock_entry = {
            "manifest_sha256": sha256_file(manifest_path),
            "artifact_sha256": sha256_directory(root),
        }
        preview = {"plugin_id": plugin_id, "root": str(root), "lock_entry": lock_entry, "dry_run": bool(dry_run)}
        if dry_run:
            return {"ok": True, "preview": preview}

        # Apply: persist search path + lock entry. (No deletion; we only add.)
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        search_paths = plugins_cfg.setdefault("search_paths", [])
        if not isinstance(search_paths, list):
            search_paths = []
            plugins_cfg["search_paths"] = search_paths
        root_text = str(root)
        if root_text not in [str(item) for item in search_paths]:
            search_paths.append(root_text)
        self._write_user_config(user_cfg)

        lockfile = self._read_lockfile()
        locks = lockfile.setdefault("plugins", {})
        if not isinstance(locks, dict):
            locks = {}
            lockfile["plugins"] = locks
        locks[plugin_id] = lock_entry
        self.lockfile_snapshot(reason="pre_install")
        self._write_lockfile(lockfile)
        return {"ok": True, "installed": True, "preview": preview}

    def plugins_plan(self) -> Dict[str, Any]:
        """EXT-05: deterministic dry-run plan for capability selection + conflicts."""
        rows = self.list_plugins()
        capabilities: dict[str, list[str]] = {}
        permissions: dict[str, dict[str, Any]] = {}
        conflicts: dict[str, list[str]] = {}
        for row in rows:
            pid = row.plugin_id
            permissions[pid] = dict(row.permissions)
            for cap in row.provides:
                capabilities.setdefault(str(cap), []).append(pid)
            if row.conflicts_blocked:
                conflicts[pid] = list(row.conflicts_blocked)
        payload = {
            "ok": True,
            "capabilities": {k: sorted(v) for k, v in sorted(capabilities.items())},
            "permissions": {k: permissions[k] for k in sorted(permissions)},
            "conflicts": {k: conflicts[k] for k in sorted(conflicts)},
        }
        plan_hash = sha256_text(canonical_dumps({k: payload[k] for k in ("capabilities", "permissions", "conflicts")}))
        payload["plan_hash"] = plan_hash
        return payload

    def plugins_apply(self, *, plan_hash: str, enable: list[str] | None = None, disable: list[str] | None = None) -> dict[str, Any]:
        """EXT-05: apply plugin enable/disable changes only if plan_hash matches current plan."""
        expected = str(self.plugins_plan().get("plan_hash") or "")
        if str(plan_hash or "").strip() != expected:
            return {"ok": False, "error": "plan_hash_mismatch", "expected": expected, "got": str(plan_hash or "").strip()}
        enable = enable if isinstance(enable, list) else []
        disable = disable if isinstance(disable, list) else []
        # Apply to user config (no deletion; only set flags).
        user_cfg = self._load_user_config()
        plugins_cfg = user_cfg.setdefault("plugins", {})
        enabled_map = plugins_cfg.setdefault("enabled", {})
        if not isinstance(enabled_map, dict):
            enabled_map = {}
            plugins_cfg["enabled"] = enabled_map
        changed: dict[str, bool] = {}
        for pid in enable:
            pid_str = str(pid).strip()
            if not pid_str:
                continue
            enabled_map[pid_str] = True
            changed[pid_str] = True
        for pid in disable:
            pid_str = str(pid).strip()
            if not pid_str:
                continue
            enabled_map[pid_str] = False
            changed[pid_str] = False
        self._write_user_config(user_cfg)
        return {"ok": True, "plan_hash": expected, "changed": {k: changed[k] for k in sorted(changed)}}

    def update_lock_entry(self, plugin_id: str, *, reason: str = "update") -> dict[str, Any]:
        """EXT-03: update a single plugin lock entry in-place (snapshot + deterministic diff)."""
        manifests = self._registry.discover_manifests()
        alias_map = self._alias_map(manifests)
        plugin_id = alias_map.get(plugin_id, plugin_id)
        manifest = self._manifest_for(plugin_id, manifests)
        if manifest is None:
            return {"ok": False, "error": "plugin_not_found", "plugin_id": plugin_id}
        lockfile = self._read_lockfile()
        locks = lockfile.setdefault("plugins", {})
        if not isinstance(locks, dict):
            locks = {}
            lockfile["plugins"] = locks
        before = locks.get(plugin_id)
        entry = {
            "manifest_sha256": sha256_file(manifest.path),
            "artifact_sha256": sha256_directory(manifest.path.parent),
        }
        pre = self.lockfile_snapshot(reason=f"pre_{reason}_{plugin_id}")
        locks[plugin_id] = entry
        self._write_lockfile(lockfile)
        post = self.lockfile_snapshot(reason=f"post_{reason}_{plugin_id}")
        diff = None
        if bool(pre.get("ok")) and bool(post.get("ok")):
            diff = self.lockfile_diff(str(pre.get("snapshot")), str(post.get("snapshot")))
        return {
            "ok": True,
            "plugin_id": plugin_id,
            "before": before,
            "after": entry,
            "pre_snapshot": pre,
            "post_snapshot": post,
            "diff": diff,
        }

    def approve_hashes(self) -> Dict[str, Any]:
        # `tools/` is not guaranteed to be importable when autocapture is installed
        # as a package (e.g., running `.venv/bin/autocapture` outside repo PYTHONPATH).
        # Fall back to loading the updater by path.
        try:
            from tools.hypervisor.scripts.update_plugin_locks import update_plugin_locks  # type: ignore

            return update_plugin_locks()
        except Exception:
            import importlib.util

            from autocapture_nx.kernel.paths import resolve_repo_path

            path = resolve_repo_path("tools/hypervisor/scripts/update_plugin_locks.py")
            spec = importlib.util.spec_from_file_location("autocapture_update_plugin_locks", str(path))
            if spec is None or spec.loader is None:
                raise RuntimeError("plugin_locks_updater_unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            updater = getattr(module, "update_plugin_locks", None)
            if not callable(updater):
                raise RuntimeError("plugin_locks_updater_missing")
            return updater()

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
