"""Run control routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class PauseRequest(BaseModel):
    minutes: float = 10


@router.post("/api/run/start")
def run_start(request: Request):
    return request.app.state.facade.run_start()


@router.post("/api/run/stop")
def run_stop(request: Request):
    return request.app.state.facade.run_stop()


@router.post("/api/run/pause")
def run_pause(req: PauseRequest, request: Request):
    return request.app.state.facade.run_pause(req.minutes)


@router.post("/api/run/resume")
def run_resume(request: Request):
    return request.app.state.facade.run_start()
