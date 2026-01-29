"""Run control routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/run/start")
def run_start(request: Request):
    return request.app.state.facade.run_start()


@router.post("/api/run/stop")
def run_stop(request: Request):
    return request.app.state.facade.run_stop()
