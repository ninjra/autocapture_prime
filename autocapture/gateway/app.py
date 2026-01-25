"""Gateway FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI

from autocapture.gateway import router


def get_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router.router)
    return app


app = get_app()
