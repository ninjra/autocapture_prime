"""Auth helpers for FastAPI UX facade."""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import Request, WebSocket

from autocapture_nx.kernel.auth import load_or_create_token


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _get_token(config: dict[str, Any]) -> str:
    return load_or_create_token(config).token


def _header_token(headers: dict[str, str]) -> str | None:
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    token = headers.get("x-ac-token") or headers.get("X-AC-Token")
    if token:
        return token.strip()
    return None


def local_only_allowed(config: dict[str, Any]) -> bool:
    web_cfg = config.get("web", {}) if isinstance(config, dict) else {}
    return not bool(web_cfg.get("allow_remote", False))


def require_local(request: Request, config: dict[str, Any]) -> bool:
    if not local_only_allowed(config):
        return True
    client = request.client
    return _is_loopback(client.host if client else None)


def token_required(method: str) -> bool:
    return method.upper() not in {"GET", "HEAD", "OPTIONS"}


def check_request_token(request: Request, config: dict[str, Any]) -> bool:
    token = _header_token(dict(request.headers))
    if not token:
        return False
    return token == _get_token(config)


def check_websocket_token(ws: WebSocket, config: dict[str, Any]) -> bool:
    if local_only_allowed(config):
        client = ws.client
        if not _is_loopback(client.host if client else None):
            return False
    token = ws.query_params.get("token") or _header_token(dict(ws.headers))
    if not token:
        return False
    return token == _get_token(config)
