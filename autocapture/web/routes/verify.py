"""Verification endpoints for ledger, anchors, and evidence."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class VerifyPathRequest(BaseModel):
    path: str | None = None


@router.post("/api/verify/ledger")
def verify_ledger(req: VerifyPathRequest, request: Request):
    return request.app.state.facade.verify_ledger(req.path)


@router.post("/api/verify/anchors")
def verify_anchors(req: VerifyPathRequest, request: Request):
    return request.app.state.facade.verify_anchors(req.path)


@router.post("/api/verify/evidence")
def verify_evidence(request: Request):
    return request.app.state.facade.verify_evidence()
