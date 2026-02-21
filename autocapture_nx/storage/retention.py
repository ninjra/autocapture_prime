"""Disk pressure + retention policy helpers.

Non-negotiables:
- No local deletion: archive/migrate only (this module does not delete).
- Fail closed: when disk is critically low, capture should halt/pause and
  surface a deterministic state instead of partially writing artifacts.

This is dependency-free (std lib only) so it can run in WSL/CI deterministically.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DiskPressureDecision:
    level: str  # "ok" | "warn" | "soft" | "critical"
    free_bytes: int
    free_gb: int
    total_bytes: int
    used_bytes: int
    warn_free_gb: int
    soft_free_gb: int
    critical_free_gb: int
    watermark_soft_mb: int
    watermark_hard_mb: int
    hard_halt: bool


def _disk_cfg(config: dict[str, Any]) -> dict[str, Any]:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    disk = storage.get("disk_pressure", {}) if isinstance(storage, dict) else {}
    return disk if isinstance(disk, dict) else {}


def _data_dir(config: dict[str, Any]) -> Path:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = storage.get("data_dir", "data") if isinstance(storage, dict) else "data"
    return Path(str(data_dir or "data"))


def evaluate_disk_pressure(config: dict[str, Any], *, data_dir: str | Path | None = None) -> DiskPressureDecision:
    disk_cfg = _disk_cfg(config)
    warn_free_gb = int(disk_cfg.get("warn_free_gb", 200) or 200)
    soft_free_gb = int(disk_cfg.get("soft_free_gb", 100) or 100)
    critical_free_gb = int(disk_cfg.get("critical_free_gb", 50) or 50)
    watermark_soft_mb = int(disk_cfg.get("watermark_soft_mb", 0) or 0)
    watermark_hard_mb = int(disk_cfg.get("watermark_hard_mb", 0) or 0)

    root = Path(data_dir) if data_dir is not None else _data_dir(config)
    usage = shutil.disk_usage(root)
    free_bytes = int(usage.free)
    total_bytes = int(usage.total)
    used_bytes = int(usage.used)
    free_gb = int(free_bytes // (1024**3))

    hard_halt = False
    level = "ok"
    if watermark_hard_mb > 0 and free_bytes <= watermark_hard_mb * 1024 * 1024:
        level = "critical"
        hard_halt = True
    elif watermark_soft_mb > 0 and free_bytes <= watermark_soft_mb * 1024 * 1024:
        level = "soft"
    elif free_gb <= critical_free_gb:
        level = "critical"
    elif free_gb <= soft_free_gb:
        level = "soft"
    elif free_gb <= warn_free_gb:
        level = "warn"

    return DiskPressureDecision(
        level=level,
        free_bytes=free_bytes,
        free_gb=free_gb,
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        warn_free_gb=warn_free_gb,
        soft_free_gb=soft_free_gb,
        critical_free_gb=critical_free_gb,
        watermark_soft_mb=watermark_soft_mb,
        watermark_hard_mb=watermark_hard_mb,
        hard_halt=bool(hard_halt),
    )


def should_pause_capture(decision: DiskPressureDecision) -> bool:
    # For now we only hard-halt on the hard watermark. The "critical" level can
    # be used to degrade/throttle, but we avoid implicitly dropping evidence.
    return bool(decision.hard_halt)

