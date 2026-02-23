"""Configuration loading, merging, and validation."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .paths import apply_path_defaults, load_json, normalize_config_paths


@dataclass(frozen=True)
class ConfigPaths:
    default_path: Path
    user_path: Path
    schema_path: Path
    backup_dir: Path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except FileNotFoundError:
        raise ConfigError(f"Missing config file: {path}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _apply_capture_preset(config: dict[str, Any]) -> dict[str, Any]:
    capture_cfg = config.get("capture")
    if not isinstance(capture_cfg, dict):
        return config
    preset_name = capture_cfg.get("mode_preset")
    if not preset_name:
        return config
    presets = capture_cfg.get("presets", {})
    if not isinstance(presets, dict):
        return config
    preset_patch = presets.get(preset_name)
    if not isinstance(preset_patch, dict):
        return config
    return _deep_merge(config, preset_patch)


def _apply_safe_mode_overrides(config: dict[str, Any]) -> dict[str, Any]:
    kernel_cfg = config.get("kernel")
    if not isinstance(kernel_cfg, dict):
        return config
    overrides = kernel_cfg.get("safe_mode_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return config
    return _deep_merge(config, overrides)


class SchemaLiteValidator:
    """Minimal schema validator supporting object/array/scalar types."""

    def validate(self, schema: dict[str, Any], data: Any, path: str = "$") -> None:
        if "const" in schema and data != schema["const"]:
            raise ConfigError(f"{path}: value {data!r} does not match const {schema['const']!r}")
        if "enum" in schema and data not in schema["enum"]:
            raise ConfigError(f"{path}: value {data!r} not in enum {schema['enum']}")

        expected_type = schema.get("type")
        if expected_type:
            self._validate_type(expected_type, data, path)

        if expected_type == "object":
            self._validate_object(schema, data, path)
        elif expected_type == "array":
            self._validate_array(schema, data, path)
        elif expected_type in ("integer", "number"):
            self._validate_number(schema, data, path)
        else:
            if isinstance(data, dict) and any(k in schema for k in ("required", "properties", "additionalProperties")):
                self._validate_object(schema, data, path)
            elif isinstance(data, list) and "items" in schema:
                self._validate_array(schema, data, path)

        if "allOf" in schema:
            for subschema in schema["allOf"]:
                self.validate(subschema, data, path)
        if "anyOf" in schema:
            if not self._matches_any(schema["anyOf"], data, path):
                raise ConfigError(f"{path}: did not match anyOf schema")
        if "oneOf" in schema:
            matches = 0
            for subschema in schema["oneOf"]:
                try:
                    self.validate(subschema, data, path)
                    matches += 1
                except ConfigError:
                    continue
            if matches != 1:
                raise ConfigError(f"{path}: expected oneOf match, got {matches}")

    def _matches_any(self, schemas: list[dict[str, Any]], data: Any, path: str) -> bool:
        for subschema in schemas:
            try:
                self.validate(subschema, data, path)
                return True
            except ConfigError:
                continue
        return False

    def _validate_type(self, expected: str | list[str], data: Any, path: str) -> None:
        type_map: dict[str, type | tuple[type, ...]] = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "null": type(None),
        }
        if isinstance(expected, list):
            for typ in expected:
                try:
                    self._validate_type(typ, data, path)
                    return
                except ConfigError:
                    continue
            raise ConfigError(f"{path}: expected one of {expected}, got {type(data).__name__}")
        if expected not in type_map:
            raise ConfigError(f"{path}: unsupported schema type {expected}")
        if not isinstance(data, type_map[expected]):
            raise ConfigError(f"{path}: expected {expected}, got {type(data).__name__}")
        if expected == "integer" and isinstance(data, bool):
            raise ConfigError(f"{path}: expected integer, got boolean")

    def _validate_object(self, schema: dict[str, Any], data: dict[str, Any], path: str) -> None:
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                raise ConfigError(f"{path}: missing required field {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in data.items():
            if key in properties:
                self.validate(properties[key], value, f"{path}.{key}")
            else:
                if additional is False:
                    raise ConfigError(f"{path}: unexpected field {key}")
                if isinstance(additional, dict):
                    self.validate(additional, value, f"{path}.{key}")

    def _validate_array(self, schema: dict[str, Any], data: list[Any], path: str) -> None:
        items = schema.get("items")
        if items is None:
            return
        for idx, item in enumerate(data):
            self.validate(items, item, f"{path}[{idx}]")

    def _validate_number(self, schema: dict[str, Any], data: Any, path: str) -> None:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and data < minimum:
            raise ConfigError(f"{path}: value {data} below minimum {minimum}")
        if maximum is not None and data > maximum:
            raise ConfigError(f"{path}: value {data} above maximum {maximum}")


validator = SchemaLiteValidator()


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _apply_storage_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    storage = config.get("storage")
    if not isinstance(storage, dict):
        return config

    explicit_metadata_path = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "").strip()
    if explicit_metadata_path:
        storage["metadata_path"] = explicit_metadata_path
        return config

    # Metadata-only query mode should avoid hot metadata.db stalls when a live
    # read replica is available. Keep opt-out for diagnostics.
    allow_live_metadata = _env_flag("AUTOCAPTURE_QUERY_METADATA_USE_LIVE_DB", default=True)
    if _env_flag("AUTOCAPTURE_QUERY_METADATA_ONLY", default=False) and allow_live_metadata:
        metadata_path = str(storage.get("metadata_path") or "").strip()
        if metadata_path:
            live_candidate = Path(metadata_path).with_name("metadata.live.db")
            if live_candidate.exists():
                storage["metadata_path"] = str(live_candidate)
    return config


def _apply_metadata_only_query_profile(config: dict[str, Any]) -> dict[str, Any]:
    if not _env_flag("AUTOCAPTURE_QUERY_METADATA_ONLY", default=False):
        return config
    if not _env_flag("AUTOCAPTURE_QUERY_MINIMAL_PLUGINS", default=True):
        return config

    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        config["plugins"] = plugins
    plugins["safe_mode"] = True
    plugins["safe_mode_minimal"] = True

    kernel = config.get("kernel")
    if not isinstance(kernel, dict):
        kernel = {}
        config["kernel"] = kernel

    # Query metadata-only runtime needs only read/query capabilities.
    kernel["safe_mode_required_capabilities"] = [
        "storage.keyring",
        "storage.metadata",
        "storage.media",
        "ledger.writer",
        "journal.writer",
        "anchor.writer",
        "time.intent_parser",
        "retrieval.strategy",
        "answer.builder",
        "citation.validator",
    ]

    retrieval = config.get("retrieval")
    if not isinstance(retrieval, dict):
        retrieval = {}
        config["retrieval"] = retrieval
    # Keep query path deterministic and low-latency in metadata-only mode.
    retrieval["vector_enabled"] = False
    return config


def validate_config(schema_path: Path, data: dict[str, Any]) -> None:
    schema = _load_json(schema_path)
    validator.validate(schema, data)


def load_config(paths: ConfigPaths, safe_mode: bool) -> dict[str, Any]:
    defaults = _load_json(paths.default_path)
    defaults_data_dir = defaults.get("storage", {}).get("data_dir")
    if safe_mode:
        config = deepcopy(defaults)
        config.setdefault("plugins", {})["safe_mode"] = True
        user_config: dict[str, Any] = {}
    else:
        user_config = _load_json(paths.user_path) if paths.user_path.exists() else {}
        config = _deep_merge(defaults, user_config)
    config = _apply_capture_preset(config)
    if safe_mode:
        config = _apply_safe_mode_overrides(config)
    config = _apply_metadata_only_query_profile(config)
    config = _apply_storage_env_overrides(config)
    merged_data_dir = config.get("storage", {}).get("data_dir")
    config = apply_path_defaults(config, user_overrides=user_config)
    legacy_dirs = [value for value in (defaults_data_dir, merged_data_dir) if isinstance(value, str)]
    config = normalize_config_paths(config, legacy_data_dir=legacy_dirs)
    validate_config(paths.schema_path, config)
    return config


def reset_user_config(paths: ConfigPaths) -> None:
    defaults = _load_json(paths.default_path)
    backup_user_config(paths)
    paths.user_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.user_path.open("w", encoding="utf-8") as handle:
        json.dump(defaults, handle, indent=2, sort_keys=True)


def backup_user_config(paths: ConfigPaths) -> None:
    if not paths.user_path.exists():
        return
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = paths.backup_dir / "user.json"
    with paths.user_path.open("rb") as src, backup_path.open("wb") as dst:
        dst.write(src.read())


def restore_user_config(paths: ConfigPaths) -> None:
    backup_path = paths.backup_dir / "user.json"
    if not backup_path.exists():
        raise ConfigError("No backup config to restore")
    paths.user_path.parent.mkdir(parents=True, exist_ok=True)
    with backup_path.open("rb") as src, paths.user_path.open("wb") as dst:
        dst.write(src.read())
