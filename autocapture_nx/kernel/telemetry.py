"""In-process telemetry snapshot store."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any


def _copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


@dataclass
class TelemetryStore:
    max_samples: int = 120
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _latest: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _history: dict[str, list[dict[str, Any]]] = field(default_factory=dict, init=False)

    def record(self, category: str, payload: dict[str, Any]) -> None:
        if not category:
            return
        entry = _copy_payload(payload)
        with self._lock:
            self._latest[category] = entry
            history = self._history.setdefault(category, [])
            history.append(entry)
            if self.max_samples > 0 and len(history) > self.max_samples:
                del history[: len(history) - self.max_samples]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latest = {key: _copy_payload(value) for key, value in self._latest.items()}
            history = {key: [dict(item) for item in items] for key, items in self._history.items()}
        return {"latest": latest, "history": history}


_STORE = TelemetryStore()


def record_telemetry(category: str, payload: dict[str, Any]) -> None:
    _STORE.record(category, payload)


def telemetry_snapshot() -> dict[str, Any]:
    return _STORE.snapshot()
