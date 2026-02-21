"""Journal writer plugin."""

from __future__ import annotations

import json
import os
import errno
import tempfile
import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.ids import ensure_prefixed, prefixed_id
from autocapture_nx.kernel.timebase import utc_now_z, tz_offset_minutes
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


@dataclass(frozen=True)
class JournalEvent:
    schema_version: int
    event_id: str
    sequence: int
    ts_utc: str
    tzid: str
    offset_minutes: int
    event_type: str
    payload: dict[str, Any]


class JournalWriter(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        data_dir = context.config.get("storage", {}).get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "journal.ndjson")
        self._lock = threading.Lock()
        self._sequence = 0
        self._run_id = context.config.get("runtime", {}).get("run_id")
        self._tzid = context.config.get("runtime", {}).get("timezone", "UTC")

    def _is_perm_error(self, exc: BaseException) -> bool:
        if isinstance(exc, PermissionError):
            return True
        if isinstance(exc, OSError):
            return exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
        return False

    def _fallback_path(self) -> str:
        digest = hashlib.sha256(self._path.encode("utf-8")).hexdigest()[:16]
        root = os.path.join(tempfile.gettempdir(), "autocapture", "shadow_logs")
        os.makedirs(root, exist_ok=True)
        return os.path.join(root, f"{digest}.journal.ndjson")

    def _use_fallback_path(self) -> None:
        fallback = self._fallback_path()
        if fallback != self._path:
            self._path = fallback

    def _append_line(self, canonical: str) -> None:
        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(f"{canonical}\n")
                try:
                    handle.flush()
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        except Exception as exc:
            if not self._is_perm_error(exc):
                raise
            self._use_fallback_path()
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(f"{canonical}\n")
                try:
                    handle.flush()
                    os.fsync(handle.fileno())
                except OSError:
                    pass

    def capabilities(self) -> dict[str, Any]:
        return {"journal.writer": self}

    def append(self, entry: dict[str, Any]) -> None:
        required = {
            "schema_version",
            "event_id",
            "sequence",
            "ts_utc",
            "tzid",
            "offset_minutes",
            "event_type",
            "payload",
            "run_id",
        }
        with self._lock:
            if not entry.get("run_id"):
                if not self._run_id:
                    raise ValueError("Journal run_id missing")
                entry["run_id"] = self._run_id
            if "sequence" not in entry or entry.get("sequence") is None:
                entry["sequence"] = self._sequence
                self._sequence += 1
            if not entry.get("ts_utc"):
                entry["ts_utc"] = utc_now_z()
            if not entry.get("tzid"):
                entry["tzid"] = self._tzid
            if "offset_minutes" not in entry or entry.get("offset_minutes") is None:
                try:
                    dt = datetime.fromisoformat(str(entry["ts_utc"]).replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now(timezone.utc)
                entry["offset_minutes"] = tz_offset_minutes(str(entry.get("tzid") or self._tzid), at_utc=dt.astimezone(timezone.utc))
            if not entry.get("event_id"):
                entry["event_id"] = prefixed_id(entry["run_id"], entry.get("event_type", "event"), entry["sequence"])
            else:
                entry["event_id"] = ensure_prefixed(entry["run_id"], str(entry["event_id"]))
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"Journal entry missing fields: {sorted(missing)}")
        canonical = dumps(entry)
        self._append_line(canonical)

    def append_batch(self, entries: list[dict[str, Any]]) -> list[str]:
        if not entries:
            return []
        event_ids: list[str] = []
        required = {
            "schema_version",
            "event_id",
            "sequence",
            "ts_utc",
            "tzid",
            "offset_minutes",
            "event_type",
            "payload",
            "run_id",
        }
        with self._lock:
            canonicals: list[str] = []
            for entry in entries:
                if not entry.get("run_id"):
                    if not self._run_id:
                        raise ValueError("Journal run_id missing")
                    entry["run_id"] = self._run_id
                if "sequence" not in entry or entry.get("sequence") is None:
                    entry["sequence"] = self._sequence
                    self._sequence += 1
                if not entry.get("ts_utc"):
                    entry["ts_utc"] = utc_now_z()
                if not entry.get("tzid"):
                    entry["tzid"] = self._tzid
                if "offset_minutes" not in entry or entry.get("offset_minutes") is None:
                    try:
                        dt = datetime.fromisoformat(str(entry["ts_utc"]).replace("Z", "+00:00"))
                    except Exception:
                        dt = datetime.now(timezone.utc)
                    entry["offset_minutes"] = tz_offset_minutes(
                        str(entry.get("tzid") or self._tzid),
                        at_utc=dt.astimezone(timezone.utc),
                    )
                if not entry.get("event_id"):
                    entry["event_id"] = prefixed_id(entry["run_id"], entry.get("event_type", "event"), entry["sequence"])
                else:
                    entry["event_id"] = ensure_prefixed(entry["run_id"], str(entry["event_id"]))
                missing = required - set(entry.keys())
                if missing:
                    raise ValueError(f"Journal entry missing fields: {sorted(missing)}")
                canonicals.append(dumps(entry))
                event_ids.append(entry["event_id"])
            try:
                with open(self._path, "a", encoding="utf-8") as handle:
                    for canonical in canonicals:
                        handle.write(f"{canonical}\n")
                    try:
                        handle.flush()
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
            except Exception as exc:
                if not self._is_perm_error(exc):
                    raise
                self._use_fallback_path()
                with open(self._path, "a", encoding="utf-8") as handle:
                    for canonical in canonicals:
                        handle.write(f"{canonical}\n")
                    try:
                        handle.flush()
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
        return event_ids

    def append_typed(self, event: JournalEvent) -> None:
        payload = {
            "schema_version": event.schema_version,
            "event_id": event.event_id,
            "sequence": event.sequence,
            "ts_utc": event.ts_utc,
            "tzid": event.tzid,
            "offset_minutes": event.offset_minutes,
            "event_type": event.event_type,
            "payload": event.payload,
        }
        self.append(payload)

    def append_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        ts_utc: str | None = None,
        tzid: str | None = None,
        offset_minutes: int = 0,
    ) -> str:
        entry = {
            "schema_version": 1,
            "event_id": event_id,
            "sequence": None,
            "ts_utc": ts_utc,
            "tzid": tzid,
            "offset_minutes": int(offset_minutes),
            "event_type": event_type,
            "payload": payload,
            "run_id": self._run_id,
        }
        self.append(entry)
        return entry["event_id"]

    def verify(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not os.path.exists(self._path):
            return False, ["journal_missing"]
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                for idx, line in enumerate(handle):
                    if not line.strip():
                        continue
                    try:
                        _ = json.loads(line)
                    except Exception:
                        errors.append(f"journal_parse_error:{idx}")
        except Exception:
            errors.append("journal_read_failed")
        return len(errors) == 0, errors


def create_plugin(plugin_id: str, context: PluginContext) -> JournalWriter:
    return JournalWriter(plugin_id, context)
