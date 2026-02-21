"""Doctor/diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/doctor")
def doctor_status(request: Request):
    # OPS-06: lightweight doctor view (includes db_status snapshot).
    return request.app.state.facade.doctor_report()


@router.post("/api/doctor/bundle")
def create_bundle(request: Request):
    return request.app.state.facade.diagnostics_bundle_create()


@router.post("/api/doctor/self-test")
def self_test(request: Request):
    return request.app.state.facade.self_test()
