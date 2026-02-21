"""Auth routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from autocapture_nx.kernel.auth import load_or_create_token

router = APIRouter()


@router.get("/api/auth/status")
def auth_status(request: Request):
    config = request.app.state.facade.config
    web_cfg = config.get("web", {}) if isinstance(config, dict) else {}
    return {
        "token_required": True,
        "allow_remote": bool(web_cfg.get("allow_remote", False)),
        "token_path": load_or_create_token(config).path,
    }


@router.get("/api/auth/token")
def auth_token(request: Request):
    config = request.app.state.facade.config
    token = load_or_create_token(config)
    return {"token": token.token, "created_ts": token.created_ts}
