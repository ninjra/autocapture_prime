"""Auto-surfaced settings schema derived from config schema + defaults."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.errors import ConfigError


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


def build_settings_schema(schema_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    schema = _load_schema(schema_path)
    fields = _flatten_config(config, schema)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
    }
