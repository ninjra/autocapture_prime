"""Auto-surfaced settings schema derived from config schema + defaults."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.errors import ConfigError

_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "capture",
        "title": "Capture",
        "prefixes": ("capture",),
        "summary": (
            "capture.screenshot.enabled",
            "capture.video.enabled",
            "capture.audio.enabled",
            "capture.cursor.enabled",
        ),
    },
    {
        "id": "storage",
        "title": "Storage & Encryption",
        "prefixes": ("storage",),
        "summary": (
            "storage.data_dir",
            "storage.encryption_required",
            "storage.fsync_policy",
            "storage.no_deletion_mode",
            "storage.retention.evidence",
        ),
    },
    {
        "id": "privacy",
        "title": "Privacy & Egress",
        "prefixes": ("privacy", "gateway"),
        "summary": (
            "privacy.egress.enabled",
            "privacy.egress.default_sanitize",
            "privacy.egress.allow_raw_egress",
            "privacy.cloud.enabled",
        ),
    },
    {
        "id": "runtime",
        "title": "Runtime",
        "prefixes": ("runtime", "performance", "alerts"),
        "summary": (
            "runtime.idle_window_s",
            "runtime.mode_enforcement.suspend_workers",
            "runtime.telemetry.enabled",
            "performance.startup_ms",
        ),
    },
    {
        "id": "processing",
        "title": "Processing",
        "prefixes": ("processing",),
        "summary": (
            "processing.idle.enabled",
            "processing.on_query.allow_decode_extract",
            "processing.sst.enabled",
        ),
    },
    {
        "id": "models",
        "title": "Models & AI",
        "prefixes": ("models", "llm", "indexing", "retrieval"),
        "summary": (
            "llm.model",
            "models.vlm_path",
            "models.reranker_path",
            "retrieval.vector_enabled",
        ),
    },
    {
        "id": "web",
        "title": "Web & UI",
        "prefixes": ("web",),
        "summary": (
            "web.bind_port",
            "web.allow_remote",
        ),
    },
    {
        "id": "plugins",
        "title": "Plugins & Hosting",
        "prefixes": ("plugins",),
        "summary": (
            "plugins.hosting.mode",
            "plugins.locks.enforce",
        ),
    },
    {
        "id": "research",
        "title": "Research & PromptOps",
        "prefixes": ("research", "promptops"),
        "summary": (
            "research.enabled",
            "promptops.enabled",
        ),
    },
    {
        "id": "time",
        "title": "Time & Locale",
        "prefixes": ("time",),
        "summary": (
            "time.timezone",
            "runtime.timezone",
        ),
    },
)

_SENSITIVE_HINTS = ("key", "secret", "token", "password", "credential", "passphrase")


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing config schema: {path}") from exc


def _schema_for_path(schema: dict[str, Any], parts: list[str]) -> dict[str, Any] | None:
    cursor = schema
    for part in parts:
        if not isinstance(cursor, dict):
            return None
        props = cursor.get("properties")
        if not isinstance(props, dict) or part not in props:
            return None
        cursor = props.get(part, {})
    return cursor if isinstance(cursor, dict) else None


def _flatten_config(
    config: Any,
    schema: dict[str, Any] | None,
    prefix: list[str] | None = None,
) -> list[dict[str, Any]]:
    prefix = prefix or []
    fields: list[dict[str, Any]] = []

    if isinstance(config, dict):
        for key, value in config.items():
            path = prefix + [str(key)]
            sub_schema = _schema_for_path(schema, path) if schema else None
            if isinstance(value, dict) and (sub_schema or value):
                fields.extend(_flatten_config(value, schema, path))
                continue
            if isinstance(value, list) and (sub_schema and sub_schema.get("type") == "array"):
                fields.append(_field_entry(path, value, sub_schema))
                continue
            if isinstance(value, (dict, list)):
                fields.append(_field_entry(path, value, sub_schema))
                continue
            fields.append(_field_entry(path, value, sub_schema))
        return fields

    fields.append(_field_entry(prefix, config, schema))
    return fields


def _field_entry(path: list[str], value: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
    field_type = None
    if schema and "type" in schema:
        field_type = schema.get("type")
    elif isinstance(value, bool):
        field_type = "boolean"
    elif isinstance(value, int) and not isinstance(value, bool):
        field_type = "integer"
    elif isinstance(value, (float, int)):
        field_type = "number"
    elif isinstance(value, list):
        field_type = "array"
    elif isinstance(value, dict):
        field_type = "object"
    else:
        field_type = "string"

    entry = {
        "path": ".".join(path),
        "type": field_type,
        "value": value,
    }
    if schema and isinstance(schema.get("enum"), list):
        entry["enum"] = list(schema.get("enum", []))
    if schema and "minimum" in schema:
        entry["minimum"] = schema.get("minimum")
    if schema and "maximum" in schema:
        entry["maximum"] = schema.get("maximum")
    return entry


def _load_defaults(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _pretty_label(text: str) -> str:
    return text.replace("_", " ").strip().title()


def _is_sensitive(path: str) -> bool:
    lowered = path.lower()
    return any(hint in lowered for hint in _SENSITIVE_HINTS)


def _group_for_path(path: str) -> dict[str, Any]:
    prefix = path.split(".", 1)[0] if path else ""
    for group in _GROUPS:
        if prefix in group.get("prefixes", ()):
            return group
    return {"id": "other", "title": "Other", "prefixes": (), "summary": ()}


def _schema_description(schema: dict[str, Any] | None) -> str | None:
    if not isinstance(schema, dict):
        return None
    if isinstance(schema.get("description"), str) and schema.get("description"):
        return str(schema.get("description"))
    if isinstance(schema.get("title"), str) and schema.get("title"):
        return str(schema.get("title"))
    return None


def build_settings_schema(schema_path: Path, default_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    schema = _load_schema(schema_path)
    defaults = _load_defaults(default_path)
    fields = _flatten_config(config, schema)
    descriptions: dict[str, str] = {}
    groupings: list[dict[str, Any]] = []
    order_counters: dict[str, int] = {}

    for field in sorted(fields, key=lambda item: str(item.get("path", ""))):
        path = str(field.get("path", ""))
        parts = path.split(".") if path else []
        field_schema = _schema_for_path(schema, parts) if parts else None
        desc = _schema_description(field_schema) or _pretty_label(parts[-1] if parts else path)
        descriptions[path] = desc
        group = _group_for_path(path)
        group_id = str(group.get("id", "other"))
        order_counters[group_id] = order_counters.get(group_id, 0) + 1
        subgroup = parts[1] if len(parts) > 1 else ""
        summary = set(group.get("summary", ()))
        groupings.append(
            {
                "path": path,
                "ui_group": group_id,
                "ui_subgroup": str(subgroup),
                "advanced": path not in summary,
                "order": int(order_counters[group_id]),
                "sensitive": _is_sensitive(path),
                "description": desc,
            }
        )

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "defaults": defaults,
        "current": config,
        "groupings": {"fields": groupings},
        "descriptions": descriptions,
        "fields": fields,
    }
