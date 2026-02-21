"""Settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ConfigPatch(BaseModel):
    patch: dict
    confirm: str = ""


class ConfigRevert(BaseModel):
    change_id: str


@router.get("/api/config")
def config_get(request: Request):
    return request.app.state.facade.config_get()


@router.post("/api/config")
def config_set(req: ConfigPatch, request: Request):
    return request.app.state.facade.config_set(req.patch, confirm=req.confirm)


@router.get("/api/settings/schema")
def settings_schema(request: Request):
    return request.app.state.facade.settings_schema()


@router.get("/api/config/history")
def config_history(request: Request, limit: int = 20):
    return request.app.state.facade.config_history(limit=limit)


@router.get("/api/config/diff")
def config_diff(request: Request):
    return request.app.state.facade.config_diff()


@router.post("/api/config/revert")
def config_revert(req: ConfigRevert, request: Request):
    return request.app.state.facade.config_revert(req.change_id)
