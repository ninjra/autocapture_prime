"""Best-effort ACL hardening for sensitive files on Windows."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _posix_mode(is_dir: bool) -> int:
    return 0o700 if is_dir else 0o600


def harden_path_permissions(path: str | Path, *, is_dir: bool = False) -> None:
    target = Path(path)
    if os.name != "nt":
        try:
            os.chmod(target, _posix_mode(is_dir))
        except OSError:
            pass
        return
    try:
        user = os.environ.get("USERNAME") or os.getlogin()
    except Exception:
        user = None
    args = ["icacls", str(target), "/inheritance:r"]
    if user:
        rights = "F" if is_dir else "R,W"
        args += ["/grant:r", f"{user}:({rights})"]
    try:
        subprocess.run(args, check=False, capture_output=True)
    except Exception:
        return
