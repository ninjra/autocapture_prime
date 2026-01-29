"""Timeline routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/timeline")
def timeline(request: Request, limit: int = 50):
    return {"events": request.app.state.facade.journal_tail(limit=limit)}
