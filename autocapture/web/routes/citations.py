"""Citation overlay routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class OverlayRequest(BaseModel):
    span_id: str | None = None


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
