"""Query route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    schedule_extract: bool = False


@router.post("/api/query")
def query(req: QueryRequest, request: Request):
    return request.app.state.facade.query(req.query, schedule_extract=bool(req.schedule_extract))


@router.post("/api/state/query")
def state_query(req: QueryRequest, request: Request):
    return request.app.state.facade.state_query(req.query)
