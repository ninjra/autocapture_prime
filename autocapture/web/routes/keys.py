"""Keyring routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/keys")
def key_status(request: Request):
    return request.app.state.facade.keyring_status()
