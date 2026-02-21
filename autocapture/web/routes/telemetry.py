"""Telemetry websocket routes."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request

from autocapture.web.auth import check_websocket_token

router = APIRouter()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    for method in ("to_dict", "dict"):
        fn = getattr(value, method, None)
        if callable(fn):
            try:
                return _json_safe(fn())
            except Exception:
                continue
    return str(value)


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
                "telemetry": _json_safe(ws.app.state.facade.telemetry()),
                "scheduler": _json_safe(ws.app.state.facade.scheduler_status()),
                "alerts": _json_safe(ws.app.state.facade.alerts(limit=50)),
                "ts_utc": datetime.now(timezone.utc).isoformat(),
            }
            await ws.send_json(payload)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return


@router.get("/api/telemetry")
def telemetry_snapshot(request: Request):
    return {
        "telemetry": _json_safe(request.app.state.facade.telemetry()),
        "scheduler": _json_safe(request.app.state.facade.scheduler_status()),
    }
