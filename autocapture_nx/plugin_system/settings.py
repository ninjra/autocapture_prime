"""Plugin settings derivation helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _set_path(target: dict[str, Any], parts: list[str], value: Any) -> None:
    if not parts:
        return
    cursor = target
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor.get(part), dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = deepcopy(value)


def extract_paths(config: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for raw in paths:
        if not isinstance(raw, str):
            continue
        path = raw.strip()
        if not path:
            continue
        parts = [part for part in path.split(".") if part]
        if not parts:
            continue
        value: Any = config
        missing = False
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                missing = True
                break
            value = value[part]
        if missing:
            continue
        _set_path(extracted, parts, value)
    return extracted


def build_plugin_settings(
    config: dict[str, Any],
    settings_paths: list[str] | None,
    default_settings: dict[str, Any] | None,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    base: dict[str, Any] = {}
    if isinstance(default_settings, dict):
        base = deep_merge(base, default_settings)
    if settings_paths:
        base = deep_merge(base, extract_paths(config, settings_paths))
    if isinstance(overrides, dict):
        base = deep_merge(base, overrides)
    return base
