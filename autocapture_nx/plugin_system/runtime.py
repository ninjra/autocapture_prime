"""Plugin runtime helpers."""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading
from typing import Any, cast

from autocapture_nx.kernel.errors import PermissionError

_original_socket = socket.socket
_original_create_connection = socket.create_connection
_guard_local = threading.local()
_deny_global = False
_patch_lock = threading.Lock()
_patched = False


def _local_deny_count() -> int:
    return int(getattr(_guard_local, "deny_count", 0))


def _deny_count() -> int:
    return _local_deny_count()


def _set_deny_count(value: int) -> None:
    setattr(_guard_local, "deny_count", int(max(0, value)))


def set_global_network_deny(enabled: bool) -> None:
    """Deny network access process-wide when enabled."""
    global _deny_global
    _ensure_patched()
    _deny_global = bool(enabled)


def global_network_deny() -> bool:
    return bool(_deny_global)


class _GuardedSocket(_original_socket):  # type: ignore[misc]
    def __init__(self, *args, **kwargs) -> None:
        if _local_deny_count() > 0:
            raise PermissionError("Network access is denied for this plugin")
        super().__init__(*args, **kwargs)

    def connect(self, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().connect(address)

    def connect_ex(self, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().connect_ex(address)

    def bind(self, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().bind(address)

    def sendto(self, data, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().sendto(data, address)


def _create_connection_wrapper(*args, **kwargs):
    if _local_deny_count() > 0:
        raise PermissionError("Network access is denied for this plugin")
    if _deny_global:
        address = args[0] if args else kwargs.get("address")
        if address is not None and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
    return _original_create_connection(*args, **kwargs)


def _is_loopback_address(address: Any) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
        if host is None:
            return False
        if isinstance(host, bytes):
            try:
                host = host.decode("utf-8")
            except Exception:
                host = str(host)
        if isinstance(host, str):
            if host in ("localhost", "127.0.0.1", "::1"):
                return True
            if "%" in host:
                host = host.split("%", 1)[0]
            try:
                return ipaddress.ip_address(host).is_loopback
            except ValueError:
                return False
        return False
    return True


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
