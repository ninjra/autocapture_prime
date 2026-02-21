"""JSON schema registry and deterministic validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, validators

from .paths import load_json, resolve_repo_path


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str


def _path_to_str(path: Iterable[Any]) -> str:
    parts = ["$"]
    for part in path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(f".{part}")
    return "".join(parts)


def _make_validator_class():
    type_checker = Draft202012Validator.TYPE_CHECKER
    type_checker = type_checker.redefine("array", lambda _c, inst: isinstance(inst, (list, tuple)))
    # Keep objects strictly as dicts to avoid surprising mappings.
    type_checker = type_checker.redefine("object", lambda _c, inst: isinstance(inst, dict))
    return validators.extend(Draft202012Validator, type_checker=type_checker)


_Validator = _make_validator_class()


class SchemaRegistry:
    def __init__(self) -> None:
        self._schema_cache: dict[str, dict[str, Any]] = {}
        self._validator_cache: dict[int, Draft202012Validator] = {}

    def load_schema_path(self, path: str | Path) -> dict[str, Any]:
        resolved = resolve_repo_path(path)
        key = str(resolved)
        if key not in self._schema_cache:
            self._schema_cache[key] = load_json(resolved)
        return self._schema_cache[key]

    def validate(self, schema: dict[str, Any], instance: Any) -> list[SchemaIssue]:
        validator = self._validator(schema)
        errors = sorted(
            validator.iter_errors(instance),
            key=lambda err: (_path_to_str(err.absolute_path), err.message),
        )
        return [SchemaIssue(path=_path_to_str(err.absolute_path), message=err.message) for err in errors]

    def format_issues(self, issues: list[SchemaIssue]) -> str:
        return "; ".join(f"{issue.path}: {issue.message}" for issue in issues)

    def _validator(self, schema: dict[str, Any]) -> Draft202012Validator:
        key = id(schema)
        cached = self._validator_cache.get(key)
        if cached is not None:
            return cached
        validator = _Validator(schema)
        self._validator_cache[key] = validator
        return validator


def _relax_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "object" or "properties" in out:
        out.pop("required", None)
        out["additionalProperties"] = True
    if "properties" in out and isinstance(out["properties"], dict):
        out["properties"] = {k: _relax_schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        items = out["items"]
        if isinstance(items, list):
            out["items"] = [_relax_schema(item) for item in items]
        else:
            out["items"] = _relax_schema(items)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in out and isinstance(out[key], list):
            out[key] = [_relax_schema(item) for item in out[key]]
    return out


def derive_schema_from_paths(
    config_schema: dict[str, Any],
    settings_paths: list[str],
) -> dict[str, Any]:
    """Project config_schema definitions onto a minimal settings schema."""
    root: dict[str, Any] = {"type": "object", "additionalProperties": True, "properties": {}}
    for raw_path in settings_paths:
        if not isinstance(raw_path, str):
            continue
        path = raw_path.strip()
        if not path:
            continue
        parts = [part for part in path.split(".") if part]
        if not parts:
            continue
        schema_cursor = config_schema
        for part in parts:
            props = schema_cursor.get("properties") if isinstance(schema_cursor, dict) else None
            if not isinstance(props, dict) or part not in props:
                raise ValueError(f"settings_path not in config schema: {path}")
            schema_cursor = props[part]
        schema_cursor = _relax_schema(schema_cursor)
        cursor = root
        for part in parts[:-1]:
            props = cursor.setdefault("properties", {})
            if part not in props or not isinstance(props.get(part), dict):
                props[part] = {"type": "object", "additionalProperties": True, "properties": {}}
            cursor = props[part]
        cursor.setdefault("properties", {})[parts[-1]] = schema_cursor
    return root
