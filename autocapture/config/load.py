"""Configuration loading, merging, and validation for MX."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from autocapture.core.errors import ConfigError
from autocapture.core.jsonschema import validate_schema

from .defaults import env_overrides, load_default_config, load_user_config
from .models import ConfigPaths


def _load_schema(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config schema: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def validate_config(schema_path: Path, data: dict[str, Any]) -> None:
    schema = _load_schema(schema_path)
    validate_schema(schema, data)


def load_config(paths: ConfigPaths, safe_mode: bool = False) -> dict[str, Any]:
    defaults = load_default_config(paths)
    if safe_mode:
        config = deepcopy(defaults)
        config.setdefault("plugins", {})["safe_mode"] = True
    else:
        config = _deep_merge(defaults, load_user_config(paths))
    config = _deep_merge(config, env_overrides())
    validate_config(paths.schema_path, config)
    return config


def backup_user_config(paths: ConfigPaths) -> None:
    if not paths.user_path.exists():
        return
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = paths.backup_dir / "user.json"
    backup_path.write_bytes(paths.user_path.read_bytes())


def reset_user_config(paths: ConfigPaths) -> None:
    defaults = load_default_config(paths)
    backup_user_config(paths)
    paths.user_path.parent.mkdir(parents=True, exist_ok=True)
    paths.user_path.write_text(json.dumps(defaults, indent=2, sort_keys=True), encoding="utf-8")


def restore_user_config(paths: ConfigPaths) -> None:
    backup_path = paths.backup_dir / "user.json"
    if not backup_path.exists():
        raise ConfigError("No backup config to restore")
    paths.user_path.parent.mkdir(parents=True, exist_ok=True)
    paths.user_path.write_bytes(backup_path.read_bytes())
