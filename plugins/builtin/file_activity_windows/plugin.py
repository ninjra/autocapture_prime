"""File activity capture plugin (Windows watcher)."""

from __future__ import annotations

import fnmatch
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


@dataclass(frozen=True)
class _FileState:
    mtime: float
    size: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_iso(mtime: float) -> str:
    try:
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    except Exception:
        return _now_iso()


def _match_patterns(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def _iter_files(
    roots: Iterable[str],
    include_patterns: list[str],
    exclude_patterns: list[str],
    max_files: int,
) -> Iterable[tuple[str, _FileState]]:
    count = 0
    for root in roots:
        base = Path(root).expanduser()
        if not base.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(base, followlinks=False):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                if exclude_patterns and _match_patterns(path, exclude_patterns):
                    continue
                if include_patterns and not _match_patterns(path, include_patterns):
                    continue
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                count += 1
                yield str(Path(path).resolve()), _FileState(mtime=float(stat.st_mtime), size=int(stat.st_size))
                if max_files and count >= max_files:
                    return


class FileActivityWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, _FileState] = {}
        self._seq = 0

    def capabilities(self) -> dict[str, Any]:
        return {"tracking.file_activity": self}

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("File activity capture supported on Windows only")
        cfg = self.context.config.get("capture", {}).get("file_activity", {})
        if not bool(cfg.get("enabled", False)):
            return
        self._stop.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def capture_once(self) -> None:
        self._scan_and_record()

    def _run_loop(self) -> None:
        cfg = self.context.config.get("capture", {}).get("file_activity", {})
        poll = float(cfg.get("poll_interval_s", 2.0))
        poll = max(0.5, min(poll, 30.0))
        while not self._stop.is_set():
            self._scan_and_record()
            time.sleep(poll)

    def _roots(self) -> list[str]:
        cfg = self.context.config.get("capture", {}).get("file_activity", {})
        roots = cfg.get("roots", []) if isinstance(cfg, dict) else []
        roots = [str(path) for path in roots if str(path).strip()]
        if roots:
            return roots
        data_dir = self.context.config.get("storage", {}).get("data_dir", "data")
        return [str(data_dir)]

    def _scan(self) -> dict[str, _FileState]:
        cfg = self.context.config.get("capture", {}).get("file_activity", {})
        include_patterns = cfg.get("include_patterns", []) if isinstance(cfg, dict) else []
        exclude_patterns = cfg.get("exclude_patterns", []) if isinstance(cfg, dict) else []
        max_files = int(cfg.get("max_files", 20000)) if isinstance(cfg, dict) else 20000
        include_patterns = [str(item) for item in include_patterns if str(item).strip()]
        exclude_patterns = [str(item) for item in exclude_patterns if str(item).strip()]
        snapshot: dict[str, _FileState] = {}
        for path, state in _iter_files(self._roots(), include_patterns, exclude_patterns, max_files):
            snapshot[path] = state
        return snapshot

    def _scan_and_record(self) -> None:
        cfg = self.context.config.get("capture", {}).get("file_activity", {})
        max_events = int(cfg.get("max_events_per_scan", 200)) if isinstance(cfg, dict) else 200
        new_snapshot = self._scan()
        old_snapshot = self._snapshot
        created = [path for path in new_snapshot.keys() if path not in old_snapshot]
        deleted = [path for path in old_snapshot.keys() if path not in new_snapshot]
        modified = [
            path
            for path, state in new_snapshot.items()
            if path in old_snapshot and (state.mtime != old_snapshot[path].mtime or state.size != old_snapshot[path].size)
        ]
        events = [("created", p) for p in created] + [("modified", p) for p in modified] + [("deleted", p) for p in deleted]
        if max_events and len(events) > max_events:
            events = events[:max_events]
        if not events:
            self._snapshot = new_snapshot
            return
        run_id = ensure_run_id(self.context.config)
        try:
            storage_meta = self.context.get_capability("storage.metadata")
            event_builder = self.context.get_capability("event.builder")
        except Exception:
            return
        if storage_meta is None:
            return
        for operation, path in events:
            state = new_snapshot.get(path)
            ts_utc = _now_iso()
            record_id = prefixed_id(run_id, "file_activity", self._seq)
            self._seq += 1
            payload = {
                "record_type": "evidence.file.activity",
                "run_id": run_id,
                "ts_utc": ts_utc,
                "path": path,
                "operation": operation,
                "size_bytes": int(state.size) if state else None,
                "mtime_utc": _mtime_iso(state.mtime) if state else None,
                "source": "poll",
            }
            payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
            if hasattr(storage_meta, "put_new"):
                storage_meta.put_new(record_id, payload)
            else:
                storage_meta.put(record_id, payload)
            if event_builder is not None:
                event_builder.journal_event("file.activity", payload, event_id=record_id, ts_utc=ts_utc)
                event_builder.ledger_entry(
                    "file.activity",
                    inputs=[],
                    outputs=[record_id],
                    payload=payload,
                    entry_id=record_id,
                    ts_utc=ts_utc,
                )
        self._snapshot = new_snapshot


def create_plugin(plugin_id: str, context: PluginContext) -> FileActivityWindows:
    return FileActivityWindows(plugin_id, context)
