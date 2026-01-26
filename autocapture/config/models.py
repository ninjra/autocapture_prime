"""Configuration data structures for MX."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConfigPaths:
    default_path: Path
    user_path: Path
    schema_path: Path
    backup_dir: Path


@dataclass(frozen=True)
class ConfigSnapshot:
    data: dict[str, Any]
