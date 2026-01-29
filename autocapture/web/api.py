"""FastAPI app for NX web console."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from autocapture_nx.ux.facade import create_facade
from autocapture.web.auth import check_request_token, require_local, token_required
from autocapture.web.routes import alerts, auth, health, metrics, plugins, query, settings, status, verify, run, timeline, keys, egress, telemetry


def get_app() -> FastAPI:
    app = FastAPI()
    app.state.facade = create_facade(persistent=True, start_conductor=False)
    ui_dir = Path(__file__).resolve().parent / "ui"
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=ui_dir), name="ui")

        @app.get("/", include_in_schema=False)
        def ui_root():
            return FileResponse(ui_dir / "index.html")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        config = request.app.state.facade.config
        if not require_local(request, config):
            return JSONResponse(status_code=403, content={"ok": False, "error": "remote_not_allowed"})
        if token_required(request.method) and not check_request_token(request, config):
            return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})
        return await call_next(request)

    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(run.router)
    app.include_router(query.router)
    app.include_router(settings.router)
    app.include_router(verify.router)
    app.include_router(plugins.router)
    app.include_router(metrics.router)
    app.include_router(alerts.router)
    app.include_router(timeline.router)
    app.include_router(keys.router)
    app.include_router(auth.router)
    app.include_router(egress.router)
    app.include_router(telemetry.router)
    return app


app = get_app()


def create_ui_panel(plugin_id: str) -> FastAPI:
    return app


def create_ui_overlay(plugin_id: str) -> FastAPI:
    return app
