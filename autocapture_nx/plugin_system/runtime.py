"""Plugin runtime helpers."""

from __future__ import annotations

import contextlib
import socket
import threading
from typing import Any, cast

from autocapture_nx.kernel.errors import PermissionError

_original_socket = socket.socket
_original_create_connection = socket.create_connection
_guard_local = threading.local()
_patch_lock = threading.Lock()
_patched = False


def _deny_count() -> int:
    return int(getattr(_guard_local, "deny_count", 0))


def _set_deny_count(value: int) -> None:
    setattr(_guard_local, "deny_count", int(max(0, value)))


class _GuardedSocket(_original_socket):  # type: ignore[misc]
    def __init__(self, *args, **kwargs) -> None:
        if _deny_count() > 0:
            raise PermissionError("Network access is denied for this plugin")
        super().__init__(*args, **kwargs)


def _create_connection_wrapper(*args, **kwargs):
    if _deny_count() > 0:
        raise PermissionError("Network access is denied for this plugin")
    return _original_create_connection(*args, **kwargs)


def _ensure_patched() -> None:
    global _patched
    if _patched:
        return
    with _patch_lock:
        if _patched:
            return
        setattr(socket, "socket", cast(Any, _GuardedSocket))
        setattr(socket, "create_connection", cast(Any, _create_connection_wrapper))
        _patched = True


@contextlib.contextmanager
def network_guard(enabled: bool):
    """Deny network access in the current thread when enabled is False."""
    if enabled:
        yield
        return

    _ensure_patched()
    previous = _deny_count()
    _set_deny_count(previous + 1)
    try:
        yield
    finally:
        _set_deny_count(previous)
