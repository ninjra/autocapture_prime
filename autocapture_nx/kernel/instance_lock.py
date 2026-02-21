"""Exclusive instance lock for a data_dir.

Purpose: prevent concurrent writers pointing at the same dataset, which can
silently corrupt state and confuse operators.
"""

from __future__ import annotations

import os
import errno
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.errors import ConfigError


@dataclass
class InstanceLock:
    path: Path
    _handle: Any

    def close(self) -> None:
        try:
            _unlock_file(self._handle)
        except Exception:
            pass
        try:
            self._handle.close()
        except Exception:
            pass


def _lock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError as exc:
            raise ConfigError("instance_lock_held") from exc
        return
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise ConfigError("instance_lock_held") from exc


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            return
        return
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return


def _permission_denied(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        return exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
    return False


def _fallback_lock_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    base = Path(tempfile.gettempdir()) / "autocapture" / "locks"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{digest}.instance.lock"


def _open_lock_handle(path: Path):
    return path.open("a+", encoding="utf-8")


def acquire_instance_lock(data_dir: str | Path) -> InstanceLock:
    root = Path(str(data_dir)).expanduser()
    lock_path = root / ".autocapture.instance.lock"
    try:
        root.mkdir(parents=True, exist_ok=True)
        handle = _open_lock_handle(lock_path)
    except Exception as exc:
        if not _permission_denied(exc):
            raise
        lock_path = _fallback_lock_path(root)
        handle = _open_lock_handle(lock_path)
    try:
        _lock_file(handle)
    except Exception:
        try:
            handle.close()
        except Exception:
            pass
        raise
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except Exception:
            pass
    except Exception:
        # Lock is still held; best-effort metadata write.
        pass
    return InstanceLock(path=lock_path, _handle=handle)
