"""Disk-pressure spillover routing for stores.

This supports a "secondary drive" by routing *media* writes to alternate roots
when the primary volume reaches a configured pressure level.

Notes:
- This does not delete; it only chooses where to write new blobs.
- For portability/backup, the recommended way to use a different physical drive
  is to place spillover directories *under* data_dir and use an OS mountpoint/
  junction to map that directory to the other drive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from autocapture_nx.storage.retention import DiskPressureDecision, evaluate_disk_pressure


def _severity(level: str) -> int:
    text = str(level or "").strip().lower()
    if text == "critical":
        return 3
    if text == "soft":
        return 2
    if text == "warn":
        return 1
    return 0


@dataclass(frozen=True)
class SpilloverConfig:
    enabled: bool
    on_level: str  # "warn" | "soft" | "critical"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SpilloverConfig":
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        spill = storage.get("spillover", {}) if isinstance(storage, dict) else {}
        spill = spill if isinstance(spill, dict) else {}
        enabled = bool(spill.get("enabled", False))
        on_level = str(spill.get("on_level", "soft") or "soft").strip().lower()
        if on_level not in {"warn", "soft", "critical"}:
            on_level = "soft"
        return cls(enabled=enabled, on_level=on_level)


class SpilloverStore:
    """Route writes between multiple compatible stores based on disk pressure."""

    def __init__(
        self,
        *,
        config: dict[str, Any],
        stores: list[tuple[str, Any]],
        pressure_fn: Callable[[dict[str, Any], str], DiskPressureDecision] | None = None,
        telemetry: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._config = config
        self._stores = list(stores)
        self._spill_cfg = SpilloverConfig.from_config(config)
        self._pressure_fn = pressure_fn or (lambda cfg, path: evaluate_disk_pressure(cfg, data_dir=path))
        self._telemetry = telemetry

        # Keep the primary path stable for quick comparisons in hot paths.
        self._primary_path = self._stores[0][0] if self._stores else ""

    def _pick_store_for_write(self) -> tuple[str, Any]:
        # Default to primary (stores[0]).
        if not self._stores:
            raise RuntimeError("spillover_store_no_backends")
        primary_path, primary = self._stores[0]
        if not self._spill_cfg.enabled or len(self._stores) == 1:
            return primary_path, primary

        try:
            primary_pressure = self._pressure_fn(self._config, primary_path)
        except Exception:
            primary_pressure = None

        trigger = _severity(self._spill_cfg.on_level)
        if primary_pressure is None or _severity(primary_pressure.level) < trigger:
            return primary_path, primary

        # Spill when primary is at/above trigger. Choose the first candidate that
        # is strictly "better" than the primary (lower severity).
        primary_sev = _severity(primary_pressure.level)
        for path, store in self._stores[1:]:
            try:
                decision = self._pressure_fn(self._config, path)
            except Exception:
                continue
            if _severity(decision.level) < primary_sev:
                return path, store
        return primary_path, primary

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._telemetry is None:
            return
        try:
            self._telemetry(event, payload)
        except Exception:
            return

    def put_new(self, record_id: str, data: bytes, *, ts_utc: str | None = None, fsync_policy: str | None = None) -> None:
        path, store = self._pick_store_for_write()
        tried: list[str] = []
        for cand_path, cand in [(path, store)] + [s for s in self._stores if s[0] != path]:
            tried.append(cand_path)
            try:
                cand.put_new(record_id, data, ts_utc=ts_utc, fsync_policy=fsync_policy)
                if cand_path != self._primary_path:
                    self._emit(
                        "storage.media.spillover_write",
                        {"record_id": str(record_id), "ts_utc": str(ts_utc or ""), "root": str(cand_path)},
                    )
                return
            except FileExistsError:
                raise
            except OSError:
                continue
        raise OSError(f"spillover_put_new_failed tried={tried}")

    def put(self, record_id: str, data: bytes, *, ts_utc: str | None = None, fsync_policy: str | None = None) -> None:
        path, store = self._pick_store_for_write()
        try:
            store.put(record_id, data, ts_utc=ts_utc, fsync_policy=fsync_policy)
        except TypeError:
            store.put(record_id, data, ts_utc=ts_utc)
        if path != self._primary_path:
            self._emit("storage.media.spillover_write", {"record_id": str(record_id), "ts_utc": str(ts_utc or ""), "root": str(path)})

    def get(self, record_id: str, default: bytes | None = None) -> bytes | None:
        for _path, store in self._stores:
            try:
                out = store.get(record_id, default=None)
            except TypeError:
                out = store.get(record_id)
            if out is not None:
                return out
        return default

    def exists(self, record_id: str) -> bool:
        for _path, store in self._stores:
            try:
                if store.exists(record_id):
                    return True
            except Exception:
                continue
        return False

    def count(self) -> int:
        total = 0
        for _path, store in self._stores:
            try:
                total += int(store.count())
            except Exception:
                continue
        return total
