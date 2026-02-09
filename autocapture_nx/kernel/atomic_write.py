"""Atomic write helpers (temp + fsync + replace).

Used for JSON state files that must never be partially written (power loss,
crash, or interruption). NDJSON append-only logs are handled elsewhere.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except Exception:
        return
    try:
        try:
            os.fsync(fd)
        except Exception:
            return
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def atomic_write_text(path: Path, text: str, *, fsync: bool = True, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{path.name}."
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            tmp_fd = None
            handle.write(text)
            handle.flush()
            if fsync:
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
        if mode is not None:
            try:
                os.chmod(tmp_path, int(mode))
            except Exception:
                pass
        os.replace(str(tmp_path), str(path))
        if fsync:
            _fsync_dir(path.parent)
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except Exception:
                pass
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def atomic_write_bytes(path: Path, payload: bytes, *, fsync: bool = True, mode: int | None = None) -> None:
    """Atomically write raw bytes (temp + fsync + replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{path.name}."
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        with os.fdopen(tmp_fd, "wb") as handle:
            tmp_fd = None
            handle.write(payload)
            handle.flush()
            if fsync:
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
        if mode is not None:
            try:
                os.chmod(tmp_path, int(mode))
            except Exception:
                pass
        os.replace(str(tmp_path), str(path))
        if fsync:
            _fsync_dir(path.parent)
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except Exception:
                pass
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def atomic_write_json(path: Path, payload: Any, *, sort_keys: bool = True, indent: int | None = None) -> None:
    text = json.dumps(payload, sort_keys=bool(sort_keys), indent=indent)
    atomic_write_text(Path(path), text, fsync=True)
