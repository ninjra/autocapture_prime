"""Default paths and config helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.paths import default_config_dir

from .models import ConfigPaths


def _find_repo_root(start: Path | None = None) -> Path:
    override = os.getenv("AUTOCAPTURE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    cursor = start or Path(__file__).resolve()
    for parent in [cursor, *cursor.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    if len(cursor.parents) >= 2:
        return cursor.parents[2]
    return cursor.parent


def default_config_paths(root: Path | None = None) -> ConfigPaths:
    base = _find_repo_root(root)
    default_rel = "config/default.json"
    schema_rel = "contracts/config_schema.json"
    config_root = default_config_dir()
    return ConfigPaths(
        default_path=(base / default_rel).resolve(),
        user_path=(config_root / "user.json").resolve(),
        schema_path=(base / schema_rel).resolve(),
        backup_dir=(config_root / "backup").resolve(),
    )


def load_default_config(paths: ConfigPaths) -> dict[str, Any]:
    return json.loads(paths.default_path.read_text(encoding="utf-8"))


def load_user_config(paths: ConfigPaths) -> dict[str, Any]:
    if not paths.user_path.exists():
        return {}
    return json.loads(paths.user_path.read_text(encoding="utf-8"))


def env_overrides() -> dict[str, Any]:
    """Return supported env overrides.

    For now this is intentionally minimal and deterministic.
    """
    overrides: dict[str, Any] = {}
    safe_mode = os.getenv("AUTOCAPTURE_SAFE_MODE")
    if safe_mode is not None:
        overrides.setdefault("plugins", {})["safe_mode"] = safe_mode.lower() in {"1", "true", "yes"}
    return overrides
