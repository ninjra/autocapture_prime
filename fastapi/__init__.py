"""Minimal FastAPI compatibility layer with optional delegation to real FastAPI."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import typing
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def _load_real_fastapi():
    current_dir = Path(__file__).resolve().parent
    search_paths: list[str] = []
    for entry in sys.path:
        try:
            if not entry:
                continue
            resolved = Path(entry).resolve()
            if resolved == current_dir.parent:
                continue
        except Exception:
            pass
        search_paths.append(entry)
    spec = importlib.machinery.PathFinder.find_spec("fastapi", search_paths)
    if not spec or not spec.loader or not spec.origin:
        return None
    if Path(spec.origin).resolve() == Path(__file__).resolve():
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[__name__] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


_real_fastapi = _load_real_fastapi()
if _real_fastapi:
    globals().update(_real_fastapi.__dict__)
else:
    try:
        from pydantic import BaseModel, ValidationError
    except Exception:  # pragma: no cover - fallback when pydantic missing
        BaseModel = object  # type: ignore[misc,assignment]
        ValidationError = ValueError  # type: ignore[misc,assignment]

    @dataclass
    class Route:
        path: str
        methods: list[str]
        endpoint: Callable[..., Any]
        response_model: Any | None = None

    class State:
        def __init__(self) -> None:
            self.__dict__ = {}

    class Request:
        def __init__(self, app: "FastAPI", json_body: Any | None = None) -> None:
            self.app = app
            self._json = json_body

        def json(self) -> Any:
            return self._json

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None) -> None:
            super().__init__(detail or "")
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def __init__(self) -> None:
            self.routes: list[Route] = []

        def get(self, path: str, **kwargs: Any):
            return self._add_route("GET", path, **kwargs)

        def post(self, path: str, **kwargs: Any):
            return self._add_route("POST", path, **kwargs)

        def _add_route(self, method: str, path: str, **kwargs: Any):
            def decorator(func: Callable[..., Any]):
                self.routes.append(
                    Route(
                        path=path,
                        methods=[method],
                        endpoint=func,
                        response_model=kwargs.get("response_model"),
                    )
                )
                return func

            return decorator

    class FastAPI(APIRouter):
        def __init__(self) -> None:
            super().__init__()
            self.state = State()

        def include_router(self, router: APIRouter) -> None:
            self.routes.extend(router.routes)

    class Response:
        def __init__(self, status_code: int, data: Any) -> None:
            self.status_code = status_code
            self._data = data
            self.text = "" if data is None else (data if isinstance(data, str) else repr(data))

        def json(self) -> Any:
            return self._data

    def _serialize_result(result: Any) -> Any:
        if hasattr(result, "model_dump"):
            return result.model_dump()  # type: ignore[no-any-return]
        return result

    def _build_args(app: "FastAPI", endpoint: Callable[..., Any], body: Any | None):
        signature = inspect.signature(endpoint)
        try:
            hints = typing.get_type_hints(endpoint)
        except Exception:
            hints = {}
        kwargs: dict[str, Any] = {}
        for name, param in signature.parameters.items():
            annotation = hints.get(name, param.annotation)
            if annotation is inspect._empty:
                annotation = None
            if annotation is Request or name == "request":
                kwargs[name] = Request(app, body)
                continue
            if annotation is not None:
                try:
                    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                        if body is None or not isinstance(body, dict):
                            raise ValidationError("body must be object")
                        kwargs[name] = annotation.model_validate(body)  # type: ignore[attr-defined]
                        continue
                except TypeError:
                    pass
            if body is not None and isinstance(body, dict) and name in body:
                kwargs[name] = body[name]
                continue
            if param.default is not inspect._empty:
                kwargs[name] = param.default
                continue
        return kwargs

    class TestClient:
        def __init__(self, app: "FastAPI") -> None:
            self.app = app

        def get(self, path: str):
            return self._request("GET", path, None)

        def post(self, path: str, json: Any | None = None):
            return self._request("POST", path, json)

        def _request(self, method: str, path: str, json_body: Any | None):
            route = None
            for item in self.app.routes:
                if path == item.path and method in item.methods:
                    route = item
                    break
            if route is None:
                return Response(404, {"detail": "not_found"})
            try:
                kwargs = _build_args(self.app, route.endpoint, json_body)
                result = route.endpoint(**kwargs)
                return Response(200, _serialize_result(result))
            except HTTPException as exc:
                return Response(exc.status_code, {"detail": exc.detail})
            except ValidationError as exc:
                return Response(422, {"detail": str(exc)})
            except Exception as exc:  # pragma: no cover - safety net
                return Response(500, {"detail": str(exc)})

    __all__ = [
        "APIRouter",
        "FastAPI",
        "HTTPException",
        "Request",
        "TestClient",
    ]
