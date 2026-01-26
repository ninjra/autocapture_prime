"""Plugin runtime helpers."""

from __future__ import annotations

import contextlib
import socket
from typing import Any, cast

from autocapture_nx.kernel.errors import PermissionError


@contextlib.contextmanager
def network_guard(enabled: bool):
    """Deny network access when enabled is False by patching socket APIs."""
    if enabled:
        yield
        return

    original_socket = socket.socket
    original_create_connection = socket.create_connection

    def _blocked(*_args, **_kwargs):
        raise PermissionError("Network access is denied for this plugin")

    setattr(socket, "socket", cast(Any, _blocked))
    setattr(socket, "create_connection", cast(Any, _blocked))
    try:
        yield
    finally:
        setattr(socket, "socket", original_socket)
        setattr(socket, "create_connection", original_create_connection)
