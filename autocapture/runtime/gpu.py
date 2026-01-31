"""GPU coordination helpers."""

from __future__ import annotations

from typing import Any


def release_vram(*, reason: str | None = None) -> dict[str, Any]:
    """Best-effort VRAM release for common backends."""
    actions: list[str] = []
    errors: list[str] = []
    released = False

    try:
        import torch  # type: ignore

        if hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
                actions.append("torch.cuda.empty_cache")
                released = True
            except Exception as exc:
                errors.append(f"torch.empty_cache:{exc}")
            try:
                torch.cuda.ipc_collect()
                actions.append("torch.cuda.ipc_collect")
                released = True
            except Exception as exc:
                errors.append(f"torch.ipc_collect:{exc}")
    except Exception as exc:
        errors.append(f"torch.import:{exc}")

    try:
        import cupy  # type: ignore

        try:
            pool = cupy.get_default_memory_pool()
            pool.free_all_blocks()
            actions.append("cupy.pool.free_all_blocks")
            released = True
        except Exception as exc:
            errors.append(f"cupy.pool:{exc}")
    except Exception as exc:
        errors.append(f"cupy.import:{exc}")

    return {
        "ok": released or not errors,
        "released": released,
        "actions": actions,
        "errors": errors,
        "reason": reason or "",
    }
