"""Windows window metadata helpers using ctypes."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowInfo:
    title: str
    process_path: str
    hwnd: int
    rect: tuple[int, int, int, int]


def _get_foreground_window() -> int:
    user32 = ctypes.windll.user32
    return user32.GetForegroundWindow()


def _get_window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_process_path(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
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


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return (0, 0, 0, 0)


def active_window() -> Optional[WindowInfo]:
    if os.name != "nt":
        return None
    hwnd = _get_foreground_window()
    if not hwnd:
        return None
    title = _get_window_text(hwnd)
    path = _get_process_path(hwnd)
    rect = _get_window_rect(hwnd)
    return WindowInfo(title=title, process_path=path, hwnd=hwnd, rect=rect)
