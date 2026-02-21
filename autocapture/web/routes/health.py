"""Health + doctor routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
def health(request: Request):
    return request.app.state.facade.doctor_report()
