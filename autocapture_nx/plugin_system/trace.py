"""Plugin execution trace helpers."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import threading
from typing import Any, Callable


@dataclass(frozen=True)
class PluginExecutionEvent:
    plugin_id: str
    capability: str
    method: str
    start_utc: str
    end_utc: str
    duration_ms: int
    ok: bool
    error: str | None = None


class PluginExecutionTrace:
    def __init__(self, *, max_events: int = 20000) -> None:
        self._lock = threading.Lock()
        self._events: list[PluginExecutionEvent] = []
        self._max_events = max(100, int(max_events))

    def record(self, event: dict[str, Any]) -> None:
        try:
            entry = PluginExecutionEvent(**event)
        except Exception:
            return
        with self._lock:
            self._events.append(entry)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(item) for item in self._events]

    def summary(self) -> dict[str, Any]:
        counts: dict[str, dict[str, int]] = {}
        with self._lock:
            events = list(self._events)
        for event in events:
            entry = counts.setdefault(event.plugin_id, {"calls": 0, "errors": 0})
            entry["calls"] += 1
            if not event.ok:
                entry["errors"] += 1
        return {"plugins": counts, "total_calls": len(events)}


class PluginLoadReport:
    def __init__(self, fetch: Callable[[], dict[str, Any]]) -> None:
        self._fetch = fetch
        self._created_utc = datetime.now(timezone.utc).isoformat()

    def report(self) -> dict[str, Any]:
        payload = dict(self._fetch() or {})
        payload.setdefault("created_utc", self._created_utc)
        return payload
