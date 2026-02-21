"""Minimal pydantic compatibility layer with optional delegation to real pydantic."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import types
import typing
from pathlib import Path
from typing import Any, get_args, get_origin


def _load_real_pydantic():
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
    spec = importlib.machinery.PathFinder.find_spec("pydantic", search_paths)
    if not spec or not spec.loader or not spec.origin:
        return None
    if Path(spec.origin).resolve() == Path(__file__).resolve():
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[__name__] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


_real_pydantic = _load_real_pydantic()
if _real_pydantic:
    globals().update(_real_pydantic.__dict__)
else:
    class ValidationError(Exception):
        pass

    def Field(default: Any = None, **_kwargs: Any) -> Any:
        return default

    def _is_union(annotation: Any) -> bool:
        origin = get_origin(annotation)
        return origin in (types.UnionType, typing.Union)

    def _validate_value(expected: Any, value: Any) -> Any:
        if expected is Any:
            return value
        origin = get_origin(expected)
        if origin in (list, list):
            if not isinstance(value, list):
                raise ValidationError(f"expected list, got {type(value).__name__}")
            item_type = get_args(expected)[0] if get_args(expected) else Any
            return [_validate_value(item_type, item) for item in value]
        if origin is dict:
            if not isinstance(value, dict):
                raise ValidationError(f"expected dict, got {type(value).__name__}")
            return value
        if origin and _is_union(expected):
            for option in get_args(expected):
                try:
                    return _validate_value(option, value)
                except ValidationError:
                    continue
            raise ValidationError(f"expected union, got {type(value).__name__}")
        if isinstance(expected, type) and issubclass(expected, BaseModel):
            if isinstance(value, expected):
                return value
            if not isinstance(value, dict):
                raise ValidationError(f"expected {expected.__name__} object, got {type(value).__name__}")
            return expected(**value)
        if expected is None or expected is type(None):
            if value is not None:
                raise ValidationError("expected null")
            return value
        if expected in (int, float, str, bool):
            if expected is int and isinstance(value, bool):
                raise ValidationError("expected int")
            if not isinstance(value, expected):
                raise ValidationError(f"expected {expected.__name__}")
            return value
        if isinstance(expected, type):
            if not isinstance(value, expected):
                raise ValidationError(f"expected {expected.__name__}")
        return value

    class BaseModel:
        def __init__(self, **data: Any) -> None:
            values: dict[str, Any] = {}
            try:
                hints = typing.get_type_hints(self.__class__)
            except Exception:
                hints = getattr(self.__class__, "__annotations__", {})
            for field, field_type in hints.items():
                if field in data:
                    raw = data[field]
                elif hasattr(self.__class__, field):
                    raw = getattr(self.__class__, field)
                else:
                    raise ValidationError(f"missing field {field}")
                values[field] = _validate_value(field_type, raw)
            self.__dict__.update(values)

        @classmethod
        def model_validate(cls, data: Any) -> "BaseModel":
            if isinstance(data, cls):
                return data
            if not isinstance(data, dict):
                raise ValidationError("expected object")
            return cls(**data)

        def model_dump(self) -> dict[str, Any]:
            def _dump(value: Any) -> Any:
                if isinstance(value, BaseModel):
                    return value.model_dump()
                if isinstance(value, list):
                    return [_dump(item) for item in value]
                if isinstance(value, dict):
                    return {k: _dump(v) for k, v in value.items()}
                return value

            return {k: _dump(v) for k, v in self.__dict__.items()}

        def dict(self) -> dict[str, Any]:
            return self.model_dump()

    __all__ = ["BaseModel", "Field", "ValidationError"]
