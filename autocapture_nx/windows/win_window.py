"""Windows window metadata helpers using ctypes."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
import string
from typing import Optional


@dataclass
class WindowInfo:
    title: str
    process_path: str
    hwnd: int
    rect: tuple[int, int, int, int]
    monitor: "MonitorInfo | None" = None


@dataclass
class MonitorInfo:
    device: str
    rect: tuple[int, int, int, int]


def _get_foreground_window() -> int:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    return user32.GetForegroundWindow()


def _get_window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_process_path(hwnd: int) -> str:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(len(buf))
        if psapi.GetProcessImageFileNameW(handle, buf, size):
            return buf.value
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _device_path_map() -> list[tuple[str, str]]:
    if os.name != "nt":
        return []
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    mappings: list[tuple[str, str]] = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:"
        buf = ctypes.create_unicode_buffer(512)
        if kernel32.QueryDosDeviceW(drive, buf, len(buf)):
            device = buf.value
            if device:
                mappings.append((device, drive))
    # Prefer longer matches first (e.g., \\Device\\HarddiskVolume12 over \\Device\\HarddiskVolume1)
    mappings.sort(key=lambda item: len(item[0]), reverse=True)
    return mappings


def normalize_device_path(path: str, mappings: list[tuple[str, str]] | None = None) -> str:
    if not path:
        return ""
    if os.name != "nt" and mappings is None:
        return path
    mappings = mappings or _device_path_map()
    for device, drive in mappings:
        if path.lower().startswith(device.lower()):
            suffix = path[len(device):]
            if suffix.startswith("\\") or suffix.startswith("/"):
                return f"{drive}{suffix}"
            return f"{drive}\\{suffix}"
    return path


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return (0, 0, 0, 0)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]


def _get_monitor_info(hwnd: int) -> MonitorInfo | None:
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    MONITOR_DEFAULTTONEAREST = 2
    monitor_handle = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor_handle:
        return None
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
        return None
    rect = (info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom)
    return MonitorInfo(device=info.szDevice, rect=rect)


def select_monitor_for_rect(rect: tuple[int, int, int, int], monitors: list[MonitorInfo]) -> MonitorInfo | None:
    if not monitors:
        return None
    left, top, right, bottom = rect
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    for monitor in monitors:
        m_left, m_top, m_right, m_bottom = monitor.rect
        if m_left <= center_x <= m_right and m_top <= center_y <= m_bottom:
            return monitor
    return monitors[0]


def active_window() -> Optional[WindowInfo]:
    if os.name != "nt":
        return None
    hwnd = _get_foreground_window()
    if not hwnd:
        return None
    title = _get_window_text(hwnd)
    path = normalize_device_path(_get_process_path(hwnd))
    rect = _get_window_rect(hwnd)
    monitor = _get_monitor_info(hwnd)
    return WindowInfo(title=title, process_path=path, hwnd=hwnd, rect=rect, monitor=monitor)
