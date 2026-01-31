"""Media inspection routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()


@router.get("/api/media/latest")
def media_latest(request: Request, record_type: str | None = None):
    result = request.app.state.facade.media_latest(record_type=record_type)
    if "error" in result:
        status = int(result.get("status", 404))
        return JSONResponse(status_code=status, content=result)
    record_id = str(result.get("record_id") or "")
    headers = {"X-AC-Record-Id": record_id} if record_id else {}
    return Response(
        content=result["data"],
        media_type=result.get("content_type") or "application/octet-stream",
        headers=headers,
    )


@router.get("/api/media/{record_id}")
def media_get(record_id: str, request: Request):
    result = request.app.state.facade.media_get(record_id)
    if "error" in result:
        status = int(result.get("status", 404))
        return JSONResponse(status_code=status, content=result)
    record_id = str(result.get("record_id") or record_id)
    headers = {"X-AC-Record-Id": record_id} if record_id else {}
    return Response(
        content=result["data"],
        media_type=result.get("content_type") or "application/octet-stream",
        headers=headers,
    )
