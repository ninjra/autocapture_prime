"""FastAPI app for MX web console."""

from __future__ import annotations

from fastapi import FastAPI

from autocapture.ux.facade import create_facade
from autocapture.web.routes import health, query, settings, citations, plugins, metrics


def get_app() -> FastAPI:
    app = FastAPI()
    app.state.facade = create_facade()
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(settings.router)
    app.include_router(citations.router)
    app.include_router(plugins.router)
    app.include_router(metrics.router)
    return app


app = get_app()


def create_ui_panel(plugin_id: str) -> FastAPI:
    return app


def create_ui_overlay(plugin_id: str) -> FastAPI:
    return app
