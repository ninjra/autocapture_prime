"""Alerts routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/alerts")
def alerts(request: Request, limit: int = 50):
    return request.app.state.facade.alerts(limit=limit)
