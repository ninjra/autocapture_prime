"""State layer routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class JEPAModelRef(BaseModel):
    model_version: str
    training_run_id: str


class JEPALatestRequest(BaseModel):
    include_archived: bool = False


@router.get("/api/state/jepa/models")
def list_jepa_models(request: Request, archived: bool = True):
    return request.app.state.facade.state_jepa_list(include_archived=archived)


@router.post("/api/state/jepa/approve")
def approve_jepa_model(req: JEPAModelRef, request: Request):
    return request.app.state.facade.state_jepa_approve(req.model_version, req.training_run_id)


@router.post("/api/state/jepa/approve-latest")
def approve_jepa_latest(req: JEPALatestRequest, request: Request):
    return request.app.state.facade.state_jepa_approve_latest(include_archived=req.include_archived)


@router.post("/api/state/jepa/promote")
def promote_jepa_model(req: JEPAModelRef, request: Request):
    return request.app.state.facade.state_jepa_promote(req.model_version, req.training_run_id)


@router.post("/api/state/jepa/report")
def report_jepa_model(req: JEPAModelRef, request: Request):
    return request.app.state.facade.state_jepa_report(req.model_version, req.training_run_id)
