"""Plugin runtime helpers."""

from __future__ import annotations

import contextlib
import ipaddress
import os
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, cast

from autocapture_nx.kernel.errors import PermissionError

_original_socket = socket.socket
_original_create_connection = socket.create_connection
_guard_local = threading.local()
_deny_global = False
_patch_lock = threading.Lock()
_patched = False
_fs_patched = False
_fs_patch_lock = threading.Lock()
_fs_policy_local = threading.local()
_fs_policy_global = None
_original_open = None
_original_os_open = None
_original_os_listdir = None
_original_os_scandir = None
_original_os_stat = None
_original_os_lstat = None
_original_os_mkdir = None
_original_os_makedirs = None
_original_os_remove = None
_original_os_unlink = None
_original_os_rename = None
_original_os_replace = None
_original_os_rmdir = None


def _local_deny_count() -> int:
    return int(getattr(_guard_local, "deny_count", 0))


def _deny_count() -> int:
    return _local_deny_count()


def _set_deny_count(value: int) -> None:
    setattr(_guard_local, "deny_count", int(max(0, value)))


def set_global_network_deny(enabled: bool) -> None:
    """Deny network access process-wide when enabled."""
    global _deny_global
    _ensure_patched()
    _deny_global = bool(enabled)


def global_network_deny() -> bool:
    return bool(_deny_global)


class _GuardedSocket(_original_socket):  # type: ignore[misc]
    def __init__(self, *args, **kwargs) -> None:
        if _local_deny_count() > 0:
            raise PermissionError("Network access is denied for this plugin")
        super().__init__(*args, **kwargs)

    def connect(self, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().connect(address)

    def connect_ex(self, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().connect_ex(address)

    def bind(self, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().bind(address)

    def sendto(self, data, address):  # type: ignore[override]
        if _deny_global and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
        return super().sendto(data, address)


def _create_connection_wrapper(*args, **kwargs):
    if _local_deny_count() > 0:
        raise PermissionError("Network access is denied for this plugin")
    if _deny_global:
        address = args[0] if args else kwargs.get("address")
        if address is not None and not _is_loopback_address(address):
            raise PermissionError("Network access is denied for this plugin")
    return _original_create_connection(*args, **kwargs)


def _is_loopback_address(address: Any) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
        if host is None:
            return False
        if isinstance(host, bytes):
            try:
                host = host.decode("utf-8")
            except Exception:
                host = str(host)
        if isinstance(host, str):
            if host in ("localhost", "127.0.0.1", "::1"):
                return True
            if "%" in host:
                host = host.split("%", 1)[0]
            try:
                return ipaddress.ip_address(host).is_loopback
            except ValueError:
                return False
        return False
    return True


def _ensure_patched() -> None:
    global _patched
    if _patched:
        return
    with _patch_lock:
        if _patched:
            return
        setattr(socket, "socket", cast(Any, _GuardedSocket))
        setattr(socket, "create_connection", cast(Any, _create_connection_wrapper))
        _patched = True


def _normalize_root(path: Path) -> Path:
    try:
        return path.expanduser().absolute()
    except Exception:
        return path


def _normalize_roots(paths: Iterable[str | Path]) -> list[Path]:
    roots: list[Path] = []
    for raw in paths:
        if raw is None:
            continue
        root = Path(str(raw)).expanduser()
        roots.append(_normalize_root(root))
    return roots


@dataclass(frozen=True)
class FilesystemPolicy:
    read_roots: tuple[Path, ...] = field(default_factory=tuple)
    readwrite_roots: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def from_paths(
        cls,
        *,
        read: Iterable[str | Path] | None = None,
        readwrite: Iterable[str | Path] | None = None,
    ) -> "FilesystemPolicy":
        read_roots = _normalize_roots(read or [])
        write_roots = _normalize_roots(readwrite or [])
        all_read = list(read_roots)
        for root in write_roots:
            parent = root.parent
            if parent not in all_read:
                all_read.append(parent)
        for root in write_roots:
            if root not in all_read:
                all_read.append(root)
        return cls(read_roots=tuple(all_read), readwrite_roots=tuple(write_roots))

    def _allowed(self, path: Path, *, write: bool) -> bool:
        roots = self.readwrite_roots if write else self.read_roots
        if not roots:
            return False
        candidate = _normalize_root(path)
        for root in roots:
            try:
                candidate.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def allow_read(self, path: Path, *, allow_ancestor: bool = False) -> bool:
        if self._allowed(path, write=False):
            return True
        if not allow_ancestor:
            return False
        candidate = _normalize_root(path)
        for root in self.read_roots:
            try:
                root.relative_to(candidate)
                return True
            except ValueError:
                continue
        return False

    def allow_write(self, path: Path) -> bool:
        return self._allowed(path, write=True)

    def payload(self) -> dict[str, list[str]]:
        return {
            "read": [str(root) for root in self.read_roots],
            "readwrite": [str(root) for root in self.readwrite_roots],
        }


def _current_fs_policy() -> FilesystemPolicy | None:
    local = getattr(_fs_policy_local, "policy", None)
    if local is not None:
        return local
    return _fs_policy_global


def _set_fs_policy(policy: FilesystemPolicy | None) -> None:
    setattr(_fs_policy_local, "policy", policy)


def _write_mode_from_open(mode: str | None) -> bool:
    if not mode:
        return False
    for flag in ("w", "a", "x", "+"):
        if flag in mode:
            return True
    return False


def _write_mode_from_flags(flags: int) -> bool:
    if flags & os.O_WRONLY:
        return True
    if flags & os.O_RDWR:
        return True
    if flags & os.O_APPEND:
        return True
    if flags & os.O_CREAT:
        return True
    if flags & os.O_TRUNC:
        return True
    return False


def _check_fs(path: str | Path | int | None, *, write: bool, allow_ancestor: bool = False) -> None:
    policy = _current_fs_policy()
    if policy is None:
        return
    if isinstance(path, int):
        return
    if path is None:
        raise PermissionError("Filesystem access denied: missing path")
    try:
        candidate = Path(str(path))
    except Exception:
        raise PermissionError("Filesystem access denied: invalid path")
    if write:
        allowed = policy.allow_write(candidate)
    else:
        allowed = policy.allow_read(candidate, allow_ancestor=allow_ancestor)
    if not allowed:
        verb = "write" if write else "read"
        raise PermissionError(f"Filesystem access denied: {verb} {candidate}")


def _patch_filesystem() -> None:
    global _fs_patched
    if _fs_patched:
        return
    with _fs_patch_lock:
        if _fs_patched:
            return
        import builtins

        global _original_open, _original_os_open, _original_os_listdir, _original_os_scandir
        global _original_os_stat, _original_os_lstat, _original_os_mkdir, _original_os_makedirs
        global _original_os_remove, _original_os_unlink, _original_os_rename, _original_os_replace
        global _original_os_rmdir

        _original_open = builtins.open
        _original_os_open = os.open
        _original_os_listdir = os.listdir
        _original_os_scandir = os.scandir
        _original_os_stat = os.stat
        _original_os_lstat = os.lstat
        _original_os_mkdir = os.mkdir
        _original_os_makedirs = os.makedirs
        _original_os_remove = os.remove
        _original_os_unlink = os.unlink
        _original_os_rename = os.rename
        _original_os_replace = os.replace
        _original_os_rmdir = os.rmdir

        def _open(path, *args, **kwargs):
            mode = None
            if args:
                mode = args[0] if args else None
            if mode is None:
                mode = kwargs.get("mode", "r")
            _check_fs(path, write=_write_mode_from_open(str(mode)))
            return _original_open(path, *args, **kwargs)

        def _os_open(path, flags, *args, **kwargs):
            _check_fs(path, write=_write_mode_from_flags(int(flags)))
            return _original_os_open(path, flags, *args, **kwargs)

        def _os_listdir(path="."):
            _check_fs(path, write=False)
            return _original_os_listdir(path)

        def _os_scandir(path="."):
            _check_fs(path, write=False)
            return _original_os_scandir(path)

        def _os_stat(path, *args, **kwargs):
            _check_fs(path, write=False, allow_ancestor=True)
            return _original_os_stat(path, *args, **kwargs)

        def _os_lstat(path, *args, **kwargs):
            _check_fs(path, write=False, allow_ancestor=True)
            return _original_os_lstat(path, *args, **kwargs)

        def _os_mkdir(path, *args, **kwargs):
            _check_fs(path, write=True)
            return _original_os_mkdir(path, *args, **kwargs)

        def _os_makedirs(path, *args, **kwargs):
            _check_fs(path, write=True)
            return _original_os_makedirs(path, *args, **kwargs)

        def _os_remove(path, *args, **kwargs):
            _check_fs(path, write=True)
            return _original_os_remove(path, *args, **kwargs)

        def _os_unlink(path, *args, **kwargs):
            _check_fs(path, write=True)
            return _original_os_unlink(path, *args, **kwargs)

        def _os_rename(src, dst, *args, **kwargs):
            _check_fs(src, write=True)
            _check_fs(dst, write=True)
            return _original_os_rename(src, dst, *args, **kwargs)

        def _os_replace(src, dst, *args, **kwargs):
            _check_fs(src, write=True)
            _check_fs(dst, write=True)
            return _original_os_replace(src, dst, *args, **kwargs)

        def _os_rmdir(path, *args, **kwargs):
            _check_fs(path, write=True)
            return _original_os_rmdir(path, *args, **kwargs)

        builtins.open = cast(Any, _open)
        os.open = _os_open
        os.listdir = _os_listdir
        os.scandir = _os_scandir
        os.stat = _os_stat
        os.lstat = _os_lstat
        os.mkdir = _os_mkdir
        os.makedirs = cast(Any, _os_makedirs)
        os.remove = _os_remove
        os.unlink = _os_unlink
        os.rename = _os_rename
        os.replace = _os_replace
        os.rmdir = _os_rmdir
        _fs_patched = True


def set_global_filesystem_policy(policy: FilesystemPolicy | None) -> None:
    """Apply a filesystem policy globally for the process."""
    global _fs_policy_global
    _patch_filesystem()
    _fs_policy_global = policy


@contextlib.contextmanager
def filesystem_guard(policy: FilesystemPolicy | None):
    """Apply a filesystem policy for the current thread context."""
    if policy is None:
        yield
        return
    _patch_filesystem()
    previous = _current_fs_policy()
    _set_fs_policy(policy)
    try:
        yield
    finally:
        _set_fs_policy(previous)


@contextlib.contextmanager
def filesystem_guard_suspended():
    """Temporarily disable filesystem policy for the current thread."""
    previous = _current_fs_policy()
    _set_fs_policy(None)
    try:
        yield
    finally:
        _set_fs_policy(previous)


@contextlib.contextmanager
def network_guard(enabled: bool):
    """Deny network access in the current thread when enabled is False."""
    if enabled:
        yield
        return

    _ensure_patched()
    previous = _deny_count()
    _set_deny_count(previous + 1)
    try:
        yield
    finally:
        _set_deny_count(previous)
