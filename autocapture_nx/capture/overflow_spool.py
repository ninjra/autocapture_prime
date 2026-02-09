"""Durable overflow spool for screenshot capture.

Purpose
- When the primary data_dir volume is under hard disk pressure, screenshot capture
  should not silently drop evidence. Instead, we can temporarily spool encoded
  screenshot artifacts to a secondary directory (typically on a different volume).
- When the primary volume recovers, the spooled artifacts are drained into the
  canonical stores and removed from the overflow directory (keeps it empty when
  not actively used).

Notes
- The overflow spool is *not* the canonical store. Items are deleted from the spool
  only after they have been committed into canonical stores.
- This module is dependency-free so it can be tested deterministically in WSL/CI.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from autocapture_nx.kernel.atomic_write import atomic_write_bytes, atomic_write_text


@dataclass(frozen=True)
class OverflowSpoolConfig:
    enabled: bool
    root: str
    drain_interval_s: float
    max_drain_per_tick: int

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "OverflowSpoolConfig":
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        spool_cfg = storage.get("spool_overflow", {}) if isinstance(storage, dict) else {}
        spool_cfg = spool_cfg if isinstance(spool_cfg, dict) else {}
        enabled = bool(spool_cfg.get("enabled", False))
        root = str(spool_cfg.get("dir", "") or "").strip()
        drain_interval_s = float(spool_cfg.get("drain_interval_s", 2.0) or 2.0)
        max_drain = int(spool_cfg.get("max_drain_per_tick", 50) or 50)
        if drain_interval_s <= 0:
            drain_interval_s = 2.0
        if max_drain <= 0:
            max_drain = 50
        return cls(enabled=enabled and bool(root), root=root, drain_interval_s=drain_interval_s, max_drain_per_tick=max_drain)


class OverflowSpool:
    def __init__(self, cfg: OverflowSpoolConfig) -> None:
        self._cfg = cfg
        self._root = Path(cfg.root)
        self._pending = self._root / "pending"
        self._tmp = self._root / "tmp"
        self._last_drain = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.enabled)

    def ensure_dirs(self) -> None:
        if not self.enabled:
            return
        self._pending.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)

    def pending_count(self) -> int:
        if not self.enabled or not self._pending.exists():
            return 0
        try:
            return sum(1 for _ in self._pending.glob("*.json"))
        except Exception:
            return 0

    def write_item(self, *, record_id: str, payload: dict[str, Any], blob: bytes) -> None:
        """Write a pending spool item atomically.

        Layout:
        - pending/<record_id>.json : payload + pointers
        - pending/<record_id>.png  : blob bytes
        """
        if not self.enabled:
            raise RuntimeError("overflow_spool_disabled")
        self.ensure_dirs()

        safe = _safe_name(record_id)
        png_name = f"{safe}.png"
        json_name = f"{safe}.json"
        png_path = self._pending / png_name
        json_path = self._pending / json_name

        # Write PNG first; metadata references it.
        atomic_write_bytes(png_path, blob)
        meta = {
            "record_id": str(record_id),
            "created_ts": time.time(),
            "blob_path": png_name,
            "payload": payload,
        }
        atomic_write_text(json_path, json.dumps(meta, sort_keys=True))

    def drain_if_due(self, *, now: float, drain_fn: Callable[[dict[str, Any], bytes], bool]) -> dict[str, Any]:
        """Drain pending items into canonical store.

        drain_fn(meta, blob) -> True if committed and safe to remove from spool.
        """
        if not self.enabled:
            return {"drained": 0, "pending": 0, "skipped": 0, "enabled": False}
        if (now - self._last_drain) < float(self._cfg.drain_interval_s):
            return {"drained": 0, "pending": self.pending_count(), "skipped": 0, "enabled": True}
        self._last_drain = float(now)
        self.ensure_dirs()

        drained = 0
        skipped = 0
        pending_files = sorted(self._pending.glob("*.json"), key=lambda p: p.name)
        for meta_path in pending_files[: int(self._cfg.max_drain_per_tick)]:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                skipped += 1
                continue
            blob_name = str(meta.get("blob_path") or "").strip()
            if not blob_name:
                skipped += 1
                continue
            blob_path = self._pending / blob_name
            try:
                blob = blob_path.read_bytes()
            except Exception:
                skipped += 1
                continue
            ok = False
            try:
                ok = bool(drain_fn(meta, blob))
            except Exception:
                ok = False
            if not ok:
                skipped += 1
                continue
            # Keep overflow empty when not in use: remove items after commit.
            try:
                meta_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except TypeError:
                try:
                    if meta_path.exists():
                        meta_path.unlink()
                except Exception:
                    pass
            try:
                blob_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except TypeError:
                try:
                    if blob_path.exists():
                        blob_path.unlink()
                except Exception:
                    pass
            drained += 1

        return {"drained": drained, "pending": self.pending_count(), "skipped": skipped, "enabled": True}


def _safe_name(text: str) -> str:
    # record_ids are already URL-safe-ish; this is just belt+suspenders.
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(text))
