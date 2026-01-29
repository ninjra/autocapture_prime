"""Metadata inspection routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/metadata/latest")
def metadata_latest(request: Request, record_type: str | None = None, limit: int = 25):
    return request.app.state.facade.metadata_latest(record_type=record_type, limit=limit)


@router.get("/api/metadata/{record_id}")
def metadata_get(record_id: str, request: Request):
    return request.app.state.facade.metadata_get(record_id)
