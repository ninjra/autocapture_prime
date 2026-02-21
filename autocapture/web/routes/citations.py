"""Citation overlay routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class OverlayRequest(BaseModel):
    span_id: str | None = None


class CitationsRequest(BaseModel):
    citations: list[dict[str, Any]] = []


@router.post("/api/citations/overlay")
def overlay(req: OverlayRequest):
    return {
        "overlays": [
            {
                "span_id": req.span_id,
                "bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
                "image": None,
            }
        ]
    }


@router.post("/api/citations/resolve")
def resolve(req: CitationsRequest, request: Request):
    return request.app.state.facade.resolve_citations(req.citations)


@router.post("/api/citations/verify")
def verify(req: CitationsRequest, request: Request):
    return request.app.state.facade.verify_citations(req.citations)
