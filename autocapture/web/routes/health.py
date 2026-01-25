"""Health + doctor routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
def health(request: Request):
    report = request.app.state.facade.doctor_report()
    return report.to_dict()
