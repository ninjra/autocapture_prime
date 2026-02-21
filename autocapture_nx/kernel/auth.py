"""Local auth token management for UX facade."""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuthToken:
    token: str
    created_ts: str
    path: str


def _token_path(config: dict[str, Any]) -> str:
    web_cfg = config.get("web", {}) if isinstance(config, dict) else {}
    storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = storage_cfg.get("data_dir", "data")
    raw = web_cfg.get("auth_token_path")
    if isinstance(raw, str) and raw.strip():
        path = raw.strip()
    else:
        path = os.path.join(str(data_dir), "vault", "web_token.json")
    if os.path.isabs(path):
        return path
    base = Path(str(data_dir))
    candidate = Path(path)
    if candidate.parts[: len(base.parts)] == base.parts:
        return str(candidate)
    return str(base / candidate)


def _protect(data: bytes) -> tuple[bytes, bool]:
    if os.name != "nt":
        return data, False
    try:
        from autocapture_nx.windows.dpapi import protect

        return protect(data), True
    except Exception:
        return data, False


def _unprotect(data: bytes, protected: bool) -> bytes:
    if not protected:
        return data
    if os.name != "nt":
        raise RuntimeError("DPAPI unprotect requires Windows")
    from autocapture_nx.windows.dpapi import unprotect

    return unprotect(data)


def load_or_create_token(config: dict[str, Any]) -> AuthToken:
    path = _token_path(config)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        token_b64 = payload.get("token_b64", "")
        protected = bool(payload.get("protected", False))
        raw = base64.b64decode(token_b64) if token_b64 else b""
        token = _unprotect(raw, protected).decode("utf-8") if raw else ""
        created_ts = payload.get("created_ts", "")
        return AuthToken(token=token, created_ts=created_ts, path=path)
    token = secrets.token_urlsafe(32)
    created_ts = datetime.now(timezone.utc).isoformat()
    raw = token.encode("utf-8")
    protected_bytes, protected = _protect(raw)
    payload = {
        "token_b64": base64.b64encode(protected_bytes).decode("ascii"),
        "created_ts": created_ts,
        "protected": protected,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    try:
        from autocapture_nx.windows.acl import harden_path_permissions

        harden_path_permissions(path, is_dir=False)
        harden_path_permissions(os.path.dirname(path), is_dir=True)
    except Exception:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return AuthToken(token=token, created_ts=created_ts, path=path)
