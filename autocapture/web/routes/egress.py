"""Egress approval routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ApprovalRequest(BaseModel):
    approval_id: str
    ttl_s: float | None = None


@router.get("/api/egress/requests")
def list_requests(request: Request):
    return {"requests": request.app.state.facade.egress_requests()}


@router.post("/api/egress/approve")
def approve(req: ApprovalRequest, request: Request):
    return request.app.state.facade.egress_approve(req.approval_id, ttl_s=req.ttl_s)


@router.post("/api/egress/deny")
def deny(req: ApprovalRequest, request: Request):
    return request.app.state.facade.egress_deny(req.approval_id)
