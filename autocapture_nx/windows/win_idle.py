"""Win32 idle time helper (GetLastInputInfo).

This module must be safe to import on non-Windows platforms.
Unit tests should exercise the pure arithmetic helpers (wrap handling) without
requiring Win32 APIs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class _TickSnapshot:
    """Windows tick counters are milliseconds since boot."""

    now_ms: int
    last_input_ms: int
    # Whether the tick source is 32-bit (wraps) or 64-bit.
    wrap_32bit: bool


def _elapsed_ms(snapshot: _TickSnapshot) -> int:
    now = int(snapshot.now_ms)
    last = int(snapshot.last_input_ms)
    if snapshot.wrap_32bit:
        # Unsigned 32-bit wrap handling.
        return int((now - last) & 0xFFFFFFFF)
    return int(max(0, now - last))


def idle_seconds() -> float | None:
    """Return user idle time in seconds on Windows, else None.

    Uses Win32 GetLastInputInfo + GetTickCount64 (preferred) or GetTickCount.
    """

    if os.name != "nt":
        return None
    try:
        snap = _read_ticks()
    except Exception:
        return None
    if snap is None:
        return None
    try:
        ms = _elapsed_ms(snap)
    except Exception:
        return None
    return float(ms) / 1000.0


def _read_ticks() -> _TickSnapshot | None:
    """Internal: read Win32 tick counters.

    Separated for testability; callers should use idle_seconds().
    """

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return None

    # Prefer 64-bit tick if available.
    wrap_32 = False
    now_ms = None
    try:
        kernel32.GetTickCount64.restype = wintypes.ULONGLONG  # type: ignore[attr-defined]
        now_ms = int(kernel32.GetTickCount64())
    except Exception:
        now_ms = None

    if now_ms is None:
        wrap_32 = True
        try:
            kernel32.GetTickCount.restype = wintypes.DWORD  # type: ignore[attr-defined]
        except Exception:
            pass
        now_ms = int(kernel32.GetTickCount())

    last_ms = int(lii.dwTime)
    return _TickSnapshot(now_ms=int(now_ms), last_input_ms=last_ms, wrap_32bit=bool(wrap_32))

