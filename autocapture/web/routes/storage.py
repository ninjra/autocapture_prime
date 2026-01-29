"""Storage usage and forecast routes."""

from __future__ import annotations

import shutil
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/storage/forecast")
def storage_forecast(request: Request):
    return request.app.state.facade.storage_forecast()


@router.get("/api/storage/usage")
def storage_usage(request: Request):
    config = request.app.state.facade.config
    data_dir = config.get("storage", {}).get("data_dir", "data") if isinstance(config, dict) else "data"
    total, used, free = shutil.disk_usage(str(data_dir))
    return {
        "data_dir": str(data_dir),
        "total_bytes": int(total),
        "used_bytes": int(used),
        "free_bytes": int(free),
    }
