"""Bookmark routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class BookmarkCreate(BaseModel):
    note: str
    tags: list[str] | None = None


@router.get("/api/bookmarks")
def bookmarks_list(request: Request, limit: int = 20):
    return request.app.state.facade.bookmarks_list(limit=limit)


@router.post("/api/bookmarks")
def bookmarks_create(req: BookmarkCreate, request: Request):
    return request.app.state.facade.bookmark_add(req.note, tags=req.tags)
