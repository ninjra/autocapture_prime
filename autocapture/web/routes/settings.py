"""Settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/settings/schema")
def settings_schema(request: Request):
    return request.app.state.facade.settings_schema()
