"""Doctor/diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/doctor/bundle")
def create_bundle(request: Request):
    return request.app.state.facade.diagnostics_bundle_create()

