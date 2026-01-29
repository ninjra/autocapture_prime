"""Telemetry websocket routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request

from autocapture.web.auth import check_websocket_token

router = APIRouter()


@router.websocket("/api/ws/telemetry")
async def telemetry_ws(ws: WebSocket):
    config = ws.app.state.facade.config
    if not check_websocket_token(ws, config):
        await ws.close(code=4401)
        return
    await ws.accept()
    web_cfg = config.get("web", {}) if isinstance(config, dict) else {}
    interval = float(web_cfg.get("telemetry_interval_s", 1.0))
    interval = max(0.2, min(interval, 5.0))
    try:
        while True:
            payload = {
                "telemetry": ws.app.state.facade.telemetry(),
                "scheduler": ws.app.state.facade.scheduler_status(),
                "alerts": ws.app.state.facade.alerts(limit=50),
                "ts_utc": datetime.now(timezone.utc).isoformat(),
            }
            await ws.send_json(payload)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return


@router.get("/api/telemetry")
def telemetry_snapshot(request: Request):
    return {
        "telemetry": request.app.state.facade.telemetry(),
        "scheduler": request.app.state.facade.scheduler_status(),
    }
