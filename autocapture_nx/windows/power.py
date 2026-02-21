"""Windows display power status helpers."""

from __future__ import annotations

import os
import ctypes
from ctypes import wintypes
from typing import Any, cast


_POWER_INFO_MONITOR = 0x0E


def _call_nt_power_information(level: int) -> int | None:
    if os.name != "nt":
        return None
    windll = cast(Any, getattr(ctypes, "windll", None))
    if windll is None:
        return None
    try:
        powrprof = windll.PowrProf
    except Exception:
        return None
    state = wintypes.ULONG()
    status = powrprof.CallNtPowerInformation(
        wintypes.ULONG(level),
        None,
        0,
        ctypes.byref(state),
        ctypes.sizeof(state),
    )
    if status != 0:
        return None
    return int(state.value)


def monitor_power_state() -> bool | None:
    """Return True if the primary display is on, False if off, None if unknown."""
    state = _call_nt_power_information(_POWER_INFO_MONITOR)
    if state is None:
        return None
    # DEVICE_POWER_STATE: 1 = D0 (fully on), 2/3/4 = lower power states.
    return bool(state == 1)
