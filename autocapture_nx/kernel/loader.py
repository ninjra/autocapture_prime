"""Kernel bootstrap and health checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.config import ConfigPaths, load_config, validate_config
from autocapture_nx.kernel.errors import ConfigError
from autocapture_nx.plugin_system.registry import PluginRegistry

from .system import System


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str


class Kernel:
    def __init__(self, config_paths: ConfigPaths, safe_mode: bool = False) -> None:
        self.config_paths = config_paths
        self.safe_mode = safe_mode
        self.config: dict[str, Any] = {}
        self.system: System | None = None

    def boot(self) -> System:
        self.config = load_config(self.config_paths, safe_mode=self.safe_mode)
        registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
        plugins, capabilities = registry.load_plugins()

        updated = self._apply_meta_plugins(self.config, plugins)
        if updated != self.config:
            validate_config(self.config_paths.schema_path, updated)
            self.config = updated
            registry = PluginRegistry(self.config, safe_mode=self.safe_mode)
            plugins, capabilities = registry.load_plugins()

        self.system = System(config=self.config, plugins=plugins, capabilities=capabilities)
        return self.system

    def _apply_meta_plugins(self, config: dict[str, Any], plugins: list) -> dict[str, Any]:
        updated = dict(config)
        allowed_configurators = set(
            config.get("plugins", {}).get("meta", {}).get("configurator_allowed", [])
        )
        allowed_policies = set(
            config.get("plugins", {}).get("meta", {}).get("policy_allowed", [])
        )
        for plugin in plugins:
            if plugin.plugin_id in allowed_configurators and "meta.configurator" in plugin.capabilities:
                updated = plugin.instance.configure(updated)
        for plugin in plugins:
            if plugin.plugin_id in allowed_policies and "meta.policy" in plugin.capabilities:
                permissions = updated.get("plugins", {}).get("permissions", {})
                updated.setdefault("plugins", {})["permissions"] = plugin.instance.apply(permissions)
        return updated

    def doctor(self) -> list[DoctorCheck]:
        if self.system is None:
            raise ConfigError("Kernel not booted")
        checks: list[DoctorCheck] = []
        config = self.system.config
        plugin_ids = {p.plugin_id for p in self.system.plugins}

        default_pack = set(config.get("plugins", {}).get("default_pack", []))
        if config.get("plugins", {}).get("safe_mode", False):
            ok = plugin_ids.issubset(default_pack)
            checks.append(
                DoctorCheck(
                    name="safe_mode_default_pack",
                    ok=ok,
                    detail="only default pack loaded" if ok else "non-default plugin loaded",
                )
            )
        required_caps = config.get("kernel", {}).get("required_capabilities", [])
        missing = [cap for cap in required_caps if cap not in self.system.capabilities.all()]
        checks.append(
            DoctorCheck(
                name="required_capabilities",
                ok=not missing,
                detail="ok" if not missing else f"missing: {missing}",
            )
        )
        if config.get("storage", {}).get("encryption_required", False):
            ok = any(pid in plugin_ids for pid in ("builtin.storage.encrypted", "builtin.storage.sqlcipher"))
            checks.append(
                DoctorCheck(
                    name="encryption_required",
                    ok=ok,
                    detail="encrypted storage loaded" if ok else "encrypted storage missing",
                )
            )
        anchor_cfg = config.get("storage", {}).get("anchor", {})
        anchor_path = anchor_cfg.get("path")
        if anchor_path:
            data_dir = Path(config.get("storage", {}).get("data_dir", "data")).resolve()
            anchor_abs = Path(anchor_path).resolve()
            try:
                anchor_abs.relative_to(data_dir)
                ok = False
            except ValueError:
                ok = True
            checks.append(
                DoctorCheck(
                    name="anchor_separate_domain",
                    ok=ok,
                    detail="anchor store separate from data_dir" if ok else "anchor path within data_dir",
                )
            )
        allowed_network = set(
            config.get("plugins", {})
            .get("permissions", {})
            .get("network_allowed_plugin_ids", [])
        )
        if allowed_network != {"builtin.egress.gateway"}:
            checks.append(
                DoctorCheck(
                    name="network_allowlist",
                    ok=False,
                    detail="network allowlist must contain only builtin.egress.gateway",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    name="network_allowlist",
                    ok=True,
                    detail="ok",
                )
            )
        return checks


def default_config_paths() -> ConfigPaths:
    return ConfigPaths(
        default_path=Path("config/default.json"),
        user_path=Path("config/user.json"),
        schema_path=Path("contracts/config_schema.json"),
        backup_dir=Path("config/backup"),
    )
