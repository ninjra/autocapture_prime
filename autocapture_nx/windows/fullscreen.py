"""Fullscreen detection helpers (Windows native)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_text

try:
    from autocapture_nx.windows.win_window import active_window
except Exception:  # pragma: no cover - optional on non-Windows
    active_window = None  # type: ignore


@dataclass(frozen=True)
class FullscreenSnapshot:
    ok: bool
    fullscreen: bool
    reason: str
    ts_utc: str
    window: dict[str, Any] | None = None


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_window_ref(window_ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(window_ref, dict):
        return None
    window_value = window_ref.get("window")
    window = window_value if isinstance(window_value, dict) else window_ref
    rect = window.get("rect")
    if not isinstance(rect, (list, tuple)):
        return None
    payload: dict[str, Any] = {
        "rect": [int(v) for v in rect],
        "hwnd": int(window.get("hwnd", 0) or 0),
    }
    process_path = str(window.get("process_path", "") or "")
    if process_path:
        payload["process_path"] = process_path
        payload["process_path_hash"] = sha256_text(process_path)
    monitor = window.get("monitor")
    monitor_rect = monitor.get("rect") if isinstance(monitor, dict) else None
    if isinstance(monitor, dict) and isinstance(monitor_rect, (list, tuple)):
        payload["monitor"] = {
            "device": str(monitor.get("device", "")),
            "rect": [int(v) for v in monitor_rect],
        }
    return payload


def _window_payload_from_active() -> dict[str, Any] | None:
    if active_window is None:
        return None
    info = active_window()
    if info is None:
        return None
    payload = {
        "hwnd": int(getattr(info, "hwnd", 0) or 0),
        "rect": [int(v) for v in getattr(info, "rect", (0, 0, 0, 0))],
    }
    process_path = str(getattr(info, "process_path", "") or "")
    if process_path:
        payload["process_path"] = process_path
        payload["process_path_hash"] = sha256_text(process_path)
    monitor = getattr(info, "monitor", None)
    if monitor is not None:
        payload["monitor"] = {
            "device": str(getattr(monitor, "device", "")),
            "rect": [int(v) for v in getattr(monitor, "rect", (0, 0, 0, 0))],
        }
    return payload


def _window_fullscreen_state(window_ref: dict[str, Any] | None) -> bool | None:
    if not isinstance(window_ref, dict):
        return None
    rect = window_ref.get("rect")
    monitor = window_ref.get("monitor")
    if not isinstance(rect, (list, tuple)) or not isinstance(monitor, dict):
        return None
    monitor_rect = monitor.get("rect")
    if not isinstance(monitor_rect, (list, tuple)):
        return None
    try:
        left, top, right, bottom = [int(v) for v in rect]
        mleft, mtop, mright, mbottom = [int(v) for v in monitor_rect]
    except Exception:
        return None
    tolerance = 2
    covers = (
        left <= mleft + tolerance
        and top <= mtop + tolerance
        and right >= mright - tolerance
        and bottom >= mbottom - tolerance
    )
    return bool(covers)


def fullscreen_snapshot(window_ref: dict[str, Any] | None = None) -> FullscreenSnapshot:
    """Return fullscreen state using window metadata or Win32 active window."""
    ts_utc = _iso_utc()
    payload = _normalize_window_ref(window_ref) if window_ref else None
    if payload is None:
        if os.name != "nt":
            return FullscreenSnapshot(ok=False, fullscreen=False, reason="unsupported", ts_utc=ts_utc)
        payload = _window_payload_from_active()
    if payload is None:
        return FullscreenSnapshot(ok=False, fullscreen=False, reason="no_window", ts_utc=ts_utc)
    state = _window_fullscreen_state(payload)
    if state is None:
        return FullscreenSnapshot(ok=False, fullscreen=False, reason="missing_rect", ts_utc=ts_utc, window=payload)
    return FullscreenSnapshot(
        ok=True,
        fullscreen=bool(state),
        reason="fullscreen" if state else "windowed",
        ts_utc=ts_utc,
        window=payload,
    )
