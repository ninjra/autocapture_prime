"""Plugins route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ReloadRequest(BaseModel):
    plugin_ids: list[str] | None = None


class SettingsPatch(BaseModel):
    patch: dict


@router.get("/api/plugins")
def list_plugins(request: Request):
    return request.app.state.facade.plugins_list()


@router.get("/api/plugins/timing")
def plugins_timing(request: Request):
    return request.app.state.facade.plugins_timing()


@router.post("/api/plugins/approve")
def approve_plugins(request: Request):
    return request.app.state.facade.plugins_approve()


@router.post("/api/plugins/reload")
def reload_plugins(req: ReloadRequest, request: Request):
    return request.app.state.facade.plugins_reload(plugin_ids=req.plugin_ids)


@router.post("/api/plugins/{plugin_id}/enable")
def plugin_enable(plugin_id: str, request: Request):
    request.app.state.facade.plugins_enable(plugin_id)
    return {"ok": True}


@router.post("/api/plugins/{plugin_id}/disable")
def plugin_disable(plugin_id: str, request: Request):
    request.app.state.facade.plugins_disable(plugin_id)
    return {"ok": True}


@router.get("/api/plugins/{plugin_id}/settings")
def plugin_settings_get(plugin_id: str, request: Request):
    return request.app.state.facade.plugins_settings_get(plugin_id)


@router.post("/api/plugins/{plugin_id}/settings")
def plugin_settings_set(plugin_id: str, req: SettingsPatch, request: Request):
    return request.app.state.facade.plugins_settings_set(plugin_id, req.patch)
