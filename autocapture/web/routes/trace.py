"""Trace routes for evidence and processing."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

router = APIRouter()


class TraceProcessRequest(BaseModel):
    allow_ocr: bool = True
    allow_vlm: bool = True
    force: bool = False


@router.get("/api/trace/latest")
def trace_latest(request: Request, record_type: str | None = None):
    return request.app.state.facade.trace_latest(record_type=record_type)


@router.get("/api/trace/{record_id}")
def trace_record(record_id: str, request: Request):
    return request.app.state.facade.trace_record(record_id)


@router.get("/api/trace/{record_id}/preview")
def trace_preview(record_id: str, request: Request):
    result = request.app.state.facade.trace_preview(record_id)
    if "error" in result:
        status = int(result.get("status", 404))
        return JSONResponse(status_code=status, content=result)
    headers = {"X-AC-Record-Id": str(result.get("record_id") or record_id)}
    return Response(
        content=result["data"],
        media_type=result.get("content_type") or "application/octet-stream",
        headers=headers,
    )


@router.post("/api/trace/{record_id}/process")
def trace_process(record_id: str, req: TraceProcessRequest, request: Request):
    return request.app.state.facade.trace_process(
        record_id,
        allow_ocr=req.allow_ocr,
        allow_vlm=req.allow_vlm,
        force=req.force,
    )
