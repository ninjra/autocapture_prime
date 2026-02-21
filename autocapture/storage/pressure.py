"""Disk pressure sampling and alerting."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DiskPressureSample:
    ts_utc: str
    free_bytes: int
    total_bytes: int
    used_bytes: int
    free_gb: int
    hard_halt: bool
    evidence_bytes: int
    derived_bytes: int
    metadata_bytes: int
    lexical_bytes: int
    vector_bytes: int
    level: str


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _media_bytes_by_kind(media_dir: Path) -> tuple[int, int]:
    evidence = 0
    derived = 0
    if not media_dir.exists():
        return evidence, derived
    for root, _dirs, files in os.walk(media_dir):
        parts = set(Path(root).parts)
        is_derived = "derived" in parts
        for name in files:
            try:
                size = (Path(root) / name).stat().st_size
            except OSError:
                continue
            if is_derived:
                derived += size
            else:
                evidence += size
    return evidence, derived


def _pressure_level(free_bytes: int, free_gb: int, cfg: dict[str, Any]) -> tuple[str, bool]:
    soft_mb = int(cfg.get("watermark_soft_mb", 0) or 0)
    hard_mb = int(cfg.get("watermark_hard_mb", 0) or 0)
    if hard_mb > 0 and free_bytes <= (hard_mb * 1024 * 1024):
        return "critical", True
    if soft_mb > 0 and free_bytes <= (soft_mb * 1024 * 1024):
        return "soft", False
    warn_gb = int(cfg.get("warn_free_gb", 200))
    soft_gb = int(cfg.get("soft_free_gb", 100))
    critical_gb = int(cfg.get("critical_free_gb", 50))
    if free_gb <= critical_gb:
        return "critical", False
    if free_gb <= soft_gb:
        return "soft", False
    if free_gb <= warn_gb:
        return "warn", False
    return "ok", False


def sample_disk_pressure(config: dict[str, Any]) -> DiskPressureSample:
    storage_cfg = config.get("storage", {})
    data_dir = Path(storage_cfg.get("data_dir", "data"))
    usage = shutil.disk_usage(data_dir)
    free_bytes = int(usage.free)
    total_bytes = int(usage.total)
    used_bytes = int(usage.used)
    free_gb = int(free_bytes // (1024 ** 3))
    media_dir = Path(storage_cfg.get("media_dir", data_dir / "media"))
    evidence_bytes, derived_bytes = _media_bytes_by_kind(media_dir)
    metadata_path = Path(storage_cfg.get("metadata_path", data_dir / "metadata"))
    if not metadata_path.exists():
        alt = data_dir / "metadata"
        if alt.exists():
            metadata_path = alt
    metadata_bytes = _dir_size(metadata_path)
    lexical_path = Path(storage_cfg.get("lexical_path", data_dir / "lexical.db"))
    vector_path = Path(storage_cfg.get("vector_path", data_dir / "vector.db"))
    lexical_bytes = _dir_size(lexical_path)
    vector_bytes = _dir_size(vector_path)
    disk_cfg = storage_cfg.get("disk_pressure", {})
    level, hard_halt = _pressure_level(free_bytes, free_gb, disk_cfg if isinstance(disk_cfg, dict) else {})
    ts_utc = datetime.now(timezone.utc).isoformat()
    return DiskPressureSample(
        ts_utc=ts_utc,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        free_gb=free_gb,
        hard_halt=bool(hard_halt),
        evidence_bytes=evidence_bytes,
        derived_bytes=derived_bytes,
        metadata_bytes=metadata_bytes,
        lexical_bytes=lexical_bytes,
        vector_bytes=vector_bytes,
        level=level,
    )


def sample_payload(sample: DiskPressureSample) -> dict[str, Any]:
    return {
        "ts_utc": sample.ts_utc,
        "free_gb": sample.free_gb,
        "free_bytes": sample.free_bytes,
        "total_bytes": sample.total_bytes,
        "used_bytes": sample.used_bytes,
        "hard_halt": bool(sample.hard_halt),
        "evidence_bytes": sample.evidence_bytes,
        "derived_bytes": sample.derived_bytes,
        "metadata_bytes": sample.metadata_bytes,
        "lexical_bytes": sample.lexical_bytes,
        "vector_bytes": sample.vector_bytes,
        "level": sample.level,
    }


class StoragePressureMonitor:
    def __init__(self, system: Any) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._builder = None
        self._logger = None
        if hasattr(system, "get"):
            try:
                self._builder = system.get("event.builder")
            except Exception:
                self._builder = None
            try:
                self._logger = system.get("observability.logger")
            except Exception:
                self._logger = None
        self._last_sample = 0.0

    def _interval_s(self) -> float:
        storage_cfg = self._config.get("storage", {})
        disk_cfg = storage_cfg.get("disk_pressure", {})
        if not isinstance(disk_cfg, dict):
            return 3600.0
        return float(disk_cfg.get("interval_s", 3600))

    def due(self) -> bool:
        interval = max(60.0, self._interval_s())
        return (time.time() - self._last_sample) >= interval

    def record(self) -> DiskPressureSample | None:
        if self._builder is None:
            return None
        try:
            sample = sample_disk_pressure(self._config)
        except Exception:
            return None
        payload = sample_payload(sample)
        try:
            self._builder.journal_event("disk.pressure", payload, ts_utc=sample.ts_utc)
            self._builder.ledger_entry(
                "storage.pressure",
                inputs=[],
                outputs=[],
                payload=payload,
                ts_utc=sample.ts_utc,
            )
        except Exception:
            return None
        if self._logger is not None and sample.level in ("warn", "soft", "critical"):
            self._logger.log(
                "disk.pressure",
                {
                    "level": sample.level,
                    "free_gb": sample.free_gb,
                    "evidence_bytes": sample.evidence_bytes,
                    "derived_bytes": sample.derived_bytes,
                },
            )
        self._last_sample = time.time()
        return sample
