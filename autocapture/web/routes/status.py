"""Status routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/status")
def status(request: Request):
    return request.app.state.facade.status()
