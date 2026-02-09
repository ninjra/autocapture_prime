"""Windows screensaver state helpers."""

from __future__ import annotations

import ctypes
import os


SPI_GETSCREENSAVERRUNNING = 0x0072
WM_SYSCOMMAND = 0x0112
SC_SCREENSAVE = 0xF140
HWND_BROADCAST = 0xFFFF


def screensaver_running() -> bool | None:
    """Return True if screensaver is running, False if not, None if unsupported."""
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except Exception:
        return None


def activate_screensaver() -> bool:
    """Best-effort request to activate the configured Windows screensaver."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except Exception:
        return False
    try:
        # Use PostMessage to avoid blocking the caller thread.
        ok = user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_SCREENSAVE, 0)
        return bool(ok)
    except Exception:
        return False
    try:
        running = ctypes.c_uint(0)
        ok = user32.SystemParametersInfoW(
            SPI_GETSCREENSAVERRUNNING,
            0,
            ctypes.byref(running),
            0,
        )
        if not ok:
            return None
        return bool(running.value)
    except Exception:
        return None
