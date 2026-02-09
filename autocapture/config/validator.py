"""Config and manifest validation helpers (schema + semantic rules).

Used by fuzz/regression tests to ensure validation does not crash and failures
remain deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.schema_registry import SchemaIssue, SchemaRegistry


@dataclass(frozen=True)
class ValidationError(Exception):
    code: str
    message: str
    issues: tuple[SchemaIssue, ...] = ()

    def __str__(self) -> str:  # pragma: no cover
        base = f"{self.code}: {self.message}"
        if not self.issues:
            return base
        reg = SchemaRegistry()
        return f"{base} ({reg.format_issues(list(self.issues))})"


def validate_config(config: dict[str, Any], *, schema_path: str = "contracts/config_schema.json") -> None:
    reg = SchemaRegistry()
    schema = reg.load_schema_path(schema_path)
    issues = reg.validate(schema, config)
    if issues:
        raise ValidationError(code="config_schema_invalid", message="Config failed schema validation", issues=tuple(issues))

    # Semantic: enforce loopback-only binding even if schema allowed more.
    web = config.get("web", {}) if isinstance(config, dict) else {}
    bind = str(web.get("bind", "127.0.0.1") or "127.0.0.1")
    if bind not in {"127.0.0.1", "localhost", "::1"}:
        raise ValidationError(code="config_bind_not_loopback", message="web.bind must be loopback-only")


def validate_plugin_manifest(manifest: dict[str, Any], *, schema_path: str = "contracts/plugin_manifest.schema.json") -> None:
    reg = SchemaRegistry()
    schema = reg.load_schema_path(schema_path)
    issues = reg.validate(schema, manifest)
    if issues:
        raise ValidationError(
            code="plugin_manifest_schema_invalid",
            message="Plugin manifest failed schema validation",
            issues=tuple(issues),
        )

    # Semantic: plugin_id must be present and stable.
    plugin_id = manifest.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        raise ValidationError(code="plugin_manifest_missing_id", message="plugin_id is required")

