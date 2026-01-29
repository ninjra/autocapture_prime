"""Settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ConfigPatch(BaseModel):
    patch: dict


@router.get("/api/config")
def config_get(request: Request):
    return request.app.state.facade.config_get()


@router.post("/api/config")
def config_set(req: ConfigPatch, request: Request):
    return request.app.state.facade.config_set(req.patch)


@router.get("/api/settings/schema")
def settings_schema(request: Request):
    return request.app.state.facade.settings_schema()
