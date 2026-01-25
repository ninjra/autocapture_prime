"""Plugins route."""

from __future__ import annotations

from fastapi import APIRouter, Request

from autocapture.plugins.manager import PluginManager

router = APIRouter()


@router.get("/api/plugins")
def list_plugins(request: Request):
    config = request.app.state.facade.config
    manager = PluginManager(config, safe_mode=False)
    return {"plugins": manager.list_plugins(), "extensions": manager.list_extensions()}
