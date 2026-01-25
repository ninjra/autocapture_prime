"""TestClient shim for fastapi compatibility."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path


def _load_real_testclient():
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
    spec = importlib.machinery.PathFinder.find_spec("fastapi.testclient", search_paths)
    if not spec or not spec.loader or not spec.origin:
        return None
    if Path(spec.origin).resolve() == Path(__file__).resolve():
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[__name__] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


_real = _load_real_testclient()
if _real:
    globals().update(_real.__dict__)
else:
    from fastapi import TestClient  # noqa: F401

    __all__ = ["TestClient"]
